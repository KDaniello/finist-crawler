import hashlib
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urljoin

import jmespath
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

__all__ = ["CrawlerPlan", "FieldRule", "build_plan", "is_captcha_html", "parse_page"]

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_CAPTCHA_MARKERS = [
    "qrator",
    "ограничение доступа",
    "введите символы с картинки",
    "вы робот",
    "smartcaptcha",
    "cf-turnstile",
    "challenge-running",
    "verify you are human",
    "are you a robot",
    "подтвердите, что вы не робот",
]

# Коды типов материалов Lenta.ru
_LENTA_TYPES = {
    1: "Новость",
    2: "Статья",
    3: "Галерея",
    4: "Мнение",
    5: "Оперативный разбор",
    6: "Видео",
    8: "Онлайн",
    10: "Конференция",
    11: "Хроника",
    12: "Цикл",
    14: "Пресс-релиз",
    15: "Внешняя ссылка",
    16: "Статья Лентопедии",
    17: "Спорт",
    18: "Теперь вы знаете",
}

# Коды рубрик Lenta.ru
_LENTA_RUBRICS = {
    1: "Россия",
    2: "Мир",
    3: "Бывший СССР",
    4: "Экономика",
    37: "Силовые структуры",
    5: "Наука и техника",
    8: "Спорт",
    6: "Культура",
    7: "Интернет и СМИ",
    47: "Ценности",
    48: "Путешествия",
    9: "Из жизни",
    12: "Среда обитания",
    87: "Забота о себе",
    154: "Авто",
}


def sanitize_html(html: str) -> str:
    if not html:
        return ""
    clean = _SCRIPT_STYLE_RE.sub(" ", html)
    clean = _TAG_RE.sub(" ", clean)
    return _WHITESPACE_RE.sub(" ", clean).strip()


def is_captcha_html(html: str) -> bool:
    if not html:
        return False
    chunk = html[:8192].casefold()
    return any(marker in chunk for marker in _CAPTCHA_MARKERS)


def _generate_deterministic_id(record_data: dict[str, Any], url: str) -> str:
    author = record_data.get("author") or record_data.get("title") or ""
    text = record_data.get("text") or ""
    date = record_data.get("created_at") or ""
    if text:
        base_content = f"{author}|{text}|{date}"
    else:
        clean_data = {k: v for k, v in record_data.items() if k not in ["metadata", "message_url"]}
        base_content = json.dumps(clean_data, sort_keys=True)
    base = f"{url}|{base_content}".encode("utf-8", errors="ignore")
    return f"finist-{hashlib.md5(base).hexdigest()[:16]}"


def _extract_app_id_from_url(url: str) -> int | None:
    match = re.search(r"/appreviews/(\d+)", url)
    if match:
        return int(match.group(1))
    return None


def _extract_cursor_from_url(url: str) -> str | None:
    match = re.search(r"[?&]cursor=([^&]+)", url)
    if match:
        return urllib.parse.unquote(match.group(1))
    return None


def _ts_to_iso(ts: Any) -> str | None:
    """Конвертирует Unix timestamp (int/float/str) в ISO 8601."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC).isoformat()
    except (ValueError, TypeError, OSError):
        return str(ts)


@dataclass(frozen=True)
class FieldRule:
    selector: str
    attr: str | None = None
    default: Any = None
    regex: str | None = None


@dataclass(frozen=True)
class CrawlerPlan:
    start_urls: list[str]
    start_phase: str
    item_selector: str
    fields: dict[str, FieldRule]
    request_headers: dict[str, str]
    extraction_mode: str = "html"
    next_page_selector: str | None = None
    next_page_attr: str = "href"
    detail_item_selector: str | None = None
    detail_fields: dict[str, FieldRule] | None = None
    detail_extraction_mode: str = "html"
    detail_url_template: str | None = None
    max_pages: int = 5
    detail_max_pages: int = 0
    render_strategy: str = "auto"
    url_template: str | None = None
    pagination_mode: str = "link"
    detail_pagination_mode: str = "link"
    detail_next_page_selector: str | None = None
    detail_next_page_attr: str = "href"
    concurrency: int = 5
    requests_per_second: float = 10.0
    request_timeout_sec: int = 30
    render_wait_ms: int = 3000
    impersonate: str | None = "chrome120"


def build_plan(spec: dict[str, Any], config_overrides: dict[str, Any]) -> CrawlerPlan:
    crawler_cfg = spec.get("crawler", {})
    list_cfg = crawler_cfg.get("list", {})
    detail_cfg = crawler_cfg.get("detail", {})
    limits_cfg = crawler_cfg.get("limits", {})

    direct_urls = config_overrides.get("direct_urls", [])
    template_params = config_overrides.get("template_params", {})
    url_template = list_cfg.get("url_template")

    start_urls: list[str] = []
    start_phase = "list"
    flow: list[str] = spec.get("flow", ["list"])

    if direct_urls:
        start_urls = direct_urls
        start_phase = "detail" if flow == ["detail"] or "list" not in flow else "list"

    elif flow == ["detail"] or (flow and flow[0] == "detail"):
        detail_url_tmpl = detail_cfg.get("url_template", "")
        t_params = {**template_params}
        try:
            start_urls = [detail_url_tmpl.format(**t_params)]
            start_phase = "detail"
        except KeyError as e:
            raise ValueError(
                f"Не хватает параметра {e} для сборки detail URL. "
                f"Передайте его через template_params."
            ) from e

    elif url_template:
        t_params = list_cfg.get("url_template_params", {}).copy()
        t_params.update(template_params)
        try:
            start_urls = [url_template.format(**t_params)]
            start_phase = "list"
        except KeyError as e:
            logger.error(f"Ошибка подстановки параметров: {e}")
            raise ValueError(f"Не хватает параметра {e} для сборки URL.") from e

    else:
        start_urls = list_cfg.get("start_urls", [])
        start_phase = "list"

    if not start_urls:
        raise ValueError(
            "Не удалось определить стартовые URL. "
            "Укажите direct_urls, template_params или start_urls в YAML."
        )

    raw_headers = crawler_cfg.get("request_headers", {})
    safe_headers = {k: str(v) for k, v in raw_headers.items()}
    impersonate_val = crawler_cfg.get("impersonate", "chrome120")

    def _parse_fields(raw_fields: dict) -> dict[str, FieldRule]:
        res = {}
        for k, r in raw_fields.items():
            if isinstance(r, str):
                res[k] = FieldRule(selector=r)
            elif isinstance(r, dict):
                res[k] = FieldRule(
                    selector=r.get("selector", ""),
                    attr=r.get("attr"),
                    default=r.get("default"),
                    regex=r.get("regex"),
                )
        return res

    fields = _parse_fields(list_cfg.get("fields", {}))
    detail_fields = _parse_fields(detail_cfg.get("fields", {})) if detail_cfg else None

    detail_url_tmpl = detail_cfg.get("url_template") if detail_cfg else None
    if detail_url_tmpl and template_params:
        for key, val in template_params.items():
            detail_url_tmpl = detail_url_tmpl.replace(f"{{{key}}}", str(val))

    next_cfg = list_cfg.get("next_page", {})
    detail_next_cfg = detail_cfg.get("next_page", {}) if detail_cfg else {}
    pagination_cfg = list_cfg.get("pagination", {})
    detail_pagination_cfg = detail_cfg.get("pagination", {}) if detail_cfg else {}

    return CrawlerPlan(
        start_urls=start_urls,
        start_phase=start_phase,
        item_selector=list_cfg.get("item_selector", ""),
        fields=fields,
        request_headers=safe_headers,
        extraction_mode=list_cfg.get("extraction_mode", "html"),
        next_page_selector=next_cfg.get("selector"),
        next_page_attr=next_cfg.get("attr", "href"),
        pagination_mode=pagination_cfg.get("mode", "link"),
        detail_item_selector=detail_cfg.get("item_selector") if detail_cfg else None,
        detail_fields=detail_fields,
        detail_extraction_mode=detail_cfg.get("extraction_mode", "html") if detail_cfg else "html",
        detail_url_template=detail_url_tmpl,
        detail_next_page_selector=detail_next_cfg.get("selector"),
        detail_next_page_attr=detail_next_cfg.get("attr", "href"),
        detail_pagination_mode=detail_pagination_cfg.get("mode", "link"),
        max_pages=config_overrides.get("max_pages") or limits_cfg.get("max_pages", 5),
        detail_max_pages=config_overrides.get("detail_max_pages")
        or limits_cfg.get("detail_max_pages", 0),
        render_strategy=crawler_cfg.get("render", "auto"),
        url_template=url_template,
        concurrency=limits_cfg.get("concurrency", 5),
        requests_per_second=limits_cfg.get("requests_per_second", 10.0),
        request_timeout_sec=limits_cfg.get("request_timeout_sec", 30),
        render_wait_ms=limits_cfg.get("render_wait_ms", 3000),
        impersonate=impersonate_val,
    )


class ExtractionStrategy(Protocol):
    def extract(
        self, html: str, plan: CrawlerPlan, page_url: str, phase: str
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]: ...


class HTMLExtractor:
    def extract(self, html: str, plan: CrawlerPlan, page_url: str, phase: str):
        records = []
        next_url = None
        i_selector = plan.detail_item_selector if phase == "detail" else plan.item_selector
        f_rules = plan.detail_fields if phase == "detail" else plan.fields
        n_selector = (
            plan.detail_next_page_selector if phase == "detail" else plan.next_page_selector
        )
        n_attr = plan.detail_next_page_attr if phase == "detail" else plan.next_page_attr
        pag_mode = plan.detail_pagination_mode if phase == "detail" else plan.pagination_mode

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(i_selector)

        for item in items:
            record: dict[str, Any] = {}
            for field_name, rule in f_rules.items():
                if not rule.selector:
                    continue
                target_el = (
                    item if rule.selector in [":self", "."] else item.select_one(rule.selector)
                )
                if not target_el:
                    record[field_name] = rule.default
                    continue

                raw_text = (
                    str(target_el.get(rule.attr)).strip()
                    if rule.attr
                    else target_el.get_text(separator=" ", strip=True)
                )
                if rule.regex and raw_text and raw_text != str(rule.default):
                    m = re.search(rule.regex, raw_text)
                    if m:
                        raw_text = m.group(1)
                    else:
                        raw_text = rule.default
                record[field_name] = sanitize_html(raw_text) if field_name == "text" else raw_text

            if record:
                record["external_id"] = record.get("external_id") or _generate_deterministic_id(
                    record, page_url
                )
                record["message_url"] = page_url
                record["metadata"] = {"extracted_at": datetime.now(UTC).isoformat()}
                records.append(record)

        if n_selector:
            next_el = soup.select_one(n_selector)
            if next_el and next_el.get(n_attr):
                next_url = urljoin(page_url, str(next_el.get(n_attr)).strip())
        elif pag_mode == "offset" and records:
            try:
                step = int(n_attr)
                match = re.search(r"([&?/])(offset|page|p)(?P<sep>=|/)(\d+)", page_url)
                if match:
                    next_val = int(match.group(4)) + step
                    next_url = re.sub(
                        r"([&?/])(offset|page|p)(?:=|/)\d+",
                        rf"\1\2{match.group('sep')}{next_val}",
                        page_url,
                    )
            except Exception:
                pass

        return records, next_url, {}


class JSONExtractor:
    def extract(self, html: str, plan: CrawlerPlan, page_url: str, phase: str):
        records = []
        next_url = None
        data = None

        i_selector = plan.detail_item_selector if phase == "detail" else plan.item_selector
        f_rules = plan.detail_fields if phase == "detail" else plan.fields
        n_selector = (
            plan.detail_next_page_selector if phase == "detail" else plan.next_page_selector
        )
        n_attr = plan.detail_next_page_attr if phase == "detail" else plan.next_page_attr
        pag_mode = plan.detail_pagination_mode if phase == "detail" else plan.pagination_mode

        text_strip = html.strip()
        if text_strip.startswith("{") or text_strip.startswith("["):
            try:
                data = json.loads(text_strip)
            except json.JSONDecodeError:
                pass

        if not data:
            return records, next_url, {}

        search_target = {"_root": data} if isinstance(data, list) else data
        actual_selector = i_selector
        if isinstance(data, list) and actual_selector.startswith("["):
            actual_selector = f"_root{actual_selector}"

        items = jmespath.search(actual_selector, search_target) or []
        if not isinstance(items, list):
            items = [items]

        for item in items:
            record: dict[str, Any] = {}
            for field_name, rule in f_rules.items():
                val = jmespath.search(rule.selector, item)
                if val is None:
                    record[field_name] = rule.default
                else:
                    val_str = str(val).strip()
                    if rule.regex:
                        m = re.search(rule.regex, val_str)
                        val_str = m.group(1) if m else str(rule.default)
                    record[field_name] = sanitize_html(val_str) if field_name == "text" else val_str

            if record:
                record["external_id"] = record.get("external_id") or _generate_deterministic_id(
                    record, page_url
                )
                record["message_url"] = page_url
                record["metadata"] = {"extracted_at": datetime.now(UTC).isoformat()}
                records.append(record)

        if pag_mode == "cursor" and n_selector:
            n_val = jmespath.search(n_selector, search_target)
            if n_val and str(n_val).strip() != "None":
                if "after=" in page_url:
                    next_url = re.sub(r"([?&])after=[^&]*", rf"\g<1>after={n_val}", page_url)
                else:
                    sep = "&" if "?" in page_url else "?"
                    next_url = f"{page_url}{sep}after={n_val}"

        elif pag_mode == "offset" and records:
            try:
                step = int(n_attr)
                match = re.search(r"([&?/])(offset|page|p)(?P<sep>=|/)(\d+)", page_url)
                if match:
                    next_val = int(match.group(4)) + step
                    next_url = re.sub(
                        r"([&?/])(offset|page|p)(?:=|/)\d+",
                        rf"\1\2{match.group('sep')}{next_val}",
                        page_url,
                    )
            except Exception:
                pass

        page_meta = {"raw_api_meta": data.get("meta", {})} if isinstance(data, dict) else {}
        return records, next_url, page_meta


class LentaSearchExtractor:
    """
    Экстрактор для двухэтапного парсинга Lenta.ru.

    Этап list (extraction_mode: lenta_search):
        Разбирает ответ Search API v2. Ключевая особенность — массив
        статей лежит в ключе 'matches', а не в стандартных 'items/results'.
        Пагинация через параметр 'from' (offset).

    Этап detail (extraction_mode: lenta_article):
        Разбирает HTML страницы статьи.
        Приоритет: <script class="json-topic-info"> (структурированный JSON
        вшитый Lenta прямо в страницу) → CSS fallback.
        Автор читается из вложенного объекта author.name в json-topic-info.
    """

    # Типы материалов которые берём по умолчанию (текстовые)
    _ALLOWED_TYPES: frozenset[int] = frozenset({1, 2, 4, 5})

    def extract(
        self, html: str, plan: CrawlerPlan, page_url: str, phase: str
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
        if phase == "detail":
            return self._extract_article(html, plan, page_url)
        return self._extract_search(html, plan, page_url)

    # ------------------------------------------------------------------
    # LIST: Search API v2
    # ------------------------------------------------------------------

    def _extract_search(
        self, html: str, plan: CrawlerPlan, page_url: str
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
        records: list[dict[str, Any]] = []

        try:
            data = json.loads(html.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[LentaSearch] Невалидный JSON с {page_url}: {e}")
            return [], None, {}

        matches: list[dict] = data.get("matches", [])
        total_found: int = data.get("total_found", 0)

        if not matches:
            logger.info(f"[LentaSearch] Пустой matches[] на {page_url}")
            return [], None, {}

        for item in matches:
            item_type = item.get("type")

            # Фильтруем нетекстовые материалы (галереи, видео, онлайны)
            if item_type not in self._ALLOWED_TYPES:
                logger.debug(
                    f"[LentaSearch] Пропуск type={item_type} "
                    f"({_LENTA_TYPES.get(item_type, '?')}): {item.get('title', '')[:40]}"
                )
                continue

            article_url = item.get("url", "")
            if not article_url:
                continue

            record: dict[str, Any] = {
                # detail_url нужен движку для построения очереди detail-запросов
                "detail_url": article_url,
                # Метаданные из API — уже готовы, не нужен detail для этих полей
                "external_id": str(item.get("docid", "")),
                "title": item.get("title", ""),
                "excerpt": item.get("text", ""),
                "created_at": _ts_to_iso(item.get("pubdate")),
                "type": _LENTA_TYPES.get(item_type, str(item_type)),
                "rubric": _LENTA_RUBRICS.get(item.get("bloc"), str(item.get("bloc", ""))),
                "image_url": item.get("image_url", ""),
                "source": "lenta.ru",
            }

            record["message_url"] = article_url
            record["metadata"] = {"extracted_at": datetime.now(UTC).isoformat()}
            records.append(record)

        # Пагинация: следующая страница через from= offset
        next_url: str | None = None
        current_from = _extract_from_param(page_url)
        next_from = current_from + len(matches)

        # Останавливаемся если исчерпали доступные результаты
        # API Lenta отдаёт максимум 10,000 результатов (total)
        api_total = min(data.get("total", total_found), 10_000)
        if next_from < api_total and matches:
            next_url = re.sub(
                r"([?&])from=\d+",
                rf"\1from={next_from}",
                page_url,
            )
            logger.debug(
                f"[LentaSearch] Следующая страница: from={next_from} "
                f"(собрано {next_from}/{api_total})"
            )

        page_meta = {
            "total_found": total_found,
            "api_total": api_total,
            "current_from": current_from,
        }

        return records, next_url, page_meta

    # ------------------------------------------------------------------
    # DETAIL: HTML страницы статьи
    # ------------------------------------------------------------------

    def _extract_article(
        self, html: str, plan: CrawlerPlan, page_url: str
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
        """
        Извлекает полный текст и автора.

        Стратегия 1 (приоритет): <script class="json-topic-info">
            Lenta вшивает в каждую страницу JSON с полями:
            text, author{name, url}, dateCreated, headline и др.
            Это самый надёжный способ — не зависит от верстки.

        Стратегия 2 (fallback): CSS-селекторы
            div.topic-body__content → параграфы p.topic-body__content-text
            .topic-authors__name → автор
        """
        soup = BeautifulSoup(html, "html.parser")
        record: dict[str, Any] = {"message_url": page_url}

        # --- Стратегия 1: json-topic-info ---
        json_script = soup.select_one("script.json-topic-info")
        if json_script and json_script.string:
            try:
                topic = json.loads(json_script.string)

                text = topic.get("text", "")
                if text and len(text) > 30:
                    record["text"] = text.strip()

                # Автор — вложенный объект {"@type": "Person", "name": "..."}
                author_obj = topic.get("author")
                if isinstance(author_obj, dict):
                    record["author"] = author_obj.get("name", "")
                elif isinstance(author_obj, str):
                    record["author"] = author_obj

                # Дополнительные поля из json-topic-info
                record["description"] = topic.get("description", "")
                record["alt_headline"] = topic.get("alternativeHeadline", "")

                if record.get("text"):
                    logger.debug(
                        f"[LentaArticle] json-script OK | "
                        f"{len(record['text'])} симв. | автор: {record.get('author', '—')}"
                    )
                    record["external_id"] = _generate_deterministic_id(record, page_url)
                    record["metadata"] = {"extracted_at": datetime.now(UTC).isoformat()}
                    return [record], None, {}

            except (json.JSONDecodeError, AttributeError) as e:
                logger.debug(f"[LentaArticle] json-script failed: {e}, пробуем CSS")

        # --- Стратегия 2: CSS fallback ---
        content_el = soup.select_one("div.topic-body__content")
        if content_el:
            paragraphs = content_el.select("p.topic-body__content-text")
            if paragraphs:
                record["text"] = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
            else:
                record["text"] = content_el.get_text(separator=" ", strip=True)

        author_el = soup.select_one(".topic-authors__name")
        if author_el:
            record["author"] = author_el.get_text(strip=True)

        if record.get("text"):
            logger.debug(
                f"[LentaArticle] CSS fallback OK | "
                f"{len(record.get('text', ''))} симв. | автор: {record.get('author', '—')}"
            )
        else:
            logger.warning(f"[LentaArticle] Текст не найден на {page_url}")

        record["external_id"] = _generate_deterministic_id(record, page_url)
        record["metadata"] = {"extracted_at": datetime.now(UTC).isoformat()}
        return [record], None, {}


class SteamCursorExtractor:
    """
    Специализированный экстрактор для Steam Reviews API.

    Особенности Steam API:
    - success=1 обязателен, иначе данных нет
    - Пагинация через cursor: значение приходит в теле, нужен URL-encode
    - Конец данных: cursor не изменился ИЛИ reviews пустой
    - Конвертация времени: минуты -> часы для playtime-полей
    """

    _PLAYTIME_FIELDS = {"playtime_at_review_hours", "playtime_total_hours"}

    def extract(
        self, html: str, plan: CrawlerPlan, page_url: str, phase: str
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
        records: list[dict[str, Any]] = []

        try:
            data = json.loads(html.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[SteamExtractor] Невалидный JSON с {page_url}: {e}")
            return [], None, {}

        if data.get("success") != 1:
            logger.warning(f"[SteamExtractor] success != 1 на {page_url}")
            return [], None, {}

        f_rules = plan.detail_fields if phase == "detail" else plan.fields
        items: list[dict] = data.get("reviews", [])

        if not items:
            logger.info(f"[SteamExtractor] Отзывов больше нет на {page_url}")
            return [], None, {}

        app_id = _extract_app_id_from_url(page_url)

        for item in items:
            record: dict[str, Any] = {}

            for field_name, rule in f_rules.items():
                val = jmespath.search(rule.selector, item)

                if val is None:
                    record[field_name] = rule.default
                    continue

                if field_name in self._PLAYTIME_FIELDS:
                    try:
                        record[field_name] = round(int(val) / 60, 1)
                    except (ValueError, TypeError):
                        record[field_name] = 0.0
                    continue

                if field_name == "text":
                    record[field_name] = str(val).strip().replace("\n", " ").replace("\r", "")
                    continue

                record[field_name] = val

            if not record:
                continue

            record["game_appid"] = app_id
            record["external_id"] = (
                str(record.get("review_id"))
                if record.get("review_id")
                else _generate_deterministic_id(record, page_url)
            )
            record["message_url"] = page_url
            record["metadata"] = {"extracted_at": datetime.now(UTC).isoformat()}
            records.append(record)

        next_url: str | None = None
        new_cursor = data.get("cursor")
        current_cursor = _extract_cursor_from_url(page_url)

        if new_cursor and new_cursor != current_cursor:
            encoded_cursor = urllib.parse.quote(new_cursor, safe="")
            next_url = re.sub(
                r"([?&])cursor=[^&]*",
                rf"\1cursor={encoded_cursor}",
                page_url,
            )
            logger.debug(f"[SteamExtractor] Следующая страница: cursor={new_cursor[:25]}...")
        else:
            logger.info("[SteamExtractor] Конец отзывов (cursor не изменился).")

        page_meta = {
            "query_summary": data.get("query_summary", {}),
            "total_reviews": data.get("query_summary", {}).get("total_reviews", 0),
        }

        return records, next_url, page_meta


class RedditExtractor:
    def extract(self, html: str, plan: CrawlerPlan, page_url: str, phase: str):
        records = []
        try:
            data = json.loads(html.strip())
        except json.JSONDecodeError:
            return records, None, {}

        f_rules = plan.detail_fields if phase == "detail" else plan.fields

        if phase == "detail" and isinstance(data, list) and len(data) > 1:
            top_level = data[1].get("data", {}).get("children", [])
            post_info = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
            post_title = post_info.get("title", "")

            def extract_replies(children_list, depth=0):
                for child in children_list:
                    if child.get("kind") != "t1":
                        continue

                    c_data = child.get("data", {})
                    body = c_data.get("body")

                    if not body or body in ["[deleted]", "[removed]"]:
                        continue

                    record: dict[str, Any] = {}
                    for field_name, rule in f_rules.items():
                        val = jmespath.search(rule.selector, c_data)
                        if val is None:
                            record[field_name] = rule.default
                        else:
                            val_str = str(val).strip()
                            if field_name == "text":
                                val_str = val_str.replace("\n", " ").replace("\r", "")
                            record[field_name] = val_str

                    record["depth"] = depth
                    record["title"] = post_title
                    record["reply_to_id"] = record.get("reply_to_id") or c_data.get("parent_id")

                    if record:
                        record["external_id"] = record.get("external_id") or c_data.get("id")
                        record["message_url"] = page_url
                        record["metadata"] = {"extracted_at": datetime.now(UTC).isoformat()}
                        records.append(record)

                    replies = c_data.get("replies")
                    if isinstance(replies, dict):
                        extract_replies(replies.get("data", {}).get("children", []), depth + 1)

            extract_replies(top_level)

        return records, None, {}


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================


def _extract_from_param(url: str) -> int:
    """Извлекает текущее значение from= из URL Search API Lenta."""
    match = re.search(r"[?&]from=(\d+)", url)
    if match:
        return int(match.group(1))
    return 0


# =============================================================================
# ДИСПЕТЧЕР
# =============================================================================


def parse_page(
    html: str, plan: CrawlerPlan, page_url: str, phase: str = "list"
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    mode = plan.detail_extraction_mode if phase == "detail" else plan.extraction_mode

    if mode == "json":
        extractor: ExtractionStrategy = JSONExtractor()
    elif mode == "reddit":
        extractor = RedditExtractor()
    elif mode == "steam":
        extractor = SteamCursorExtractor()
    elif mode in ("lenta_search", "lenta_article"):
        # Один класс обрабатывает оба режима — фаза передаётся внутрь
        extractor = LentaSearchExtractor()
    else:
        extractor = HTMLExtractor()

    try:
        return extractor.extract(html, plan, page_url, phase)
    except Exception as e:
        logger.error(f"Сбой при извлечении данных с {page_url}: {e}", exc_info=True)
        return [], None, {}
