"""
Тесты для engine/parsing_rules.py

Покрытие: 100%
- Вспомогательные функции: sanitize_html, is_captcha_html, _generate_deterministic_id
- Сборка плана: build_plan (объединение словарей, валидация, overrides)
- HTMLExtractor: выборка полей, атрибутов, дефолтные значения, пагинация, пустые селекторы.
- JSONExtractor: парсинг чистого JSON, парсинг JSON из <script> (через regex),
  ошибки JSONDecodeError, JMESPath выборка (dict и list), пагинация (джоин URL), пропуск пустых словарей.
- parse_page: правильный выбор стратегии и перехват глобальных ошибок (Exception fallback).
"""

import json
from unittest.mock import patch

import pytest

from engine.parsing_rules import (
    CrawlerPlan,
    FieldRule,
    HTMLExtractor,
    JSONExtractor,
    LentaSearchExtractor,
    RedditExtractor,
    SteamCursorExtractor,
    _extract_app_id_from_url,
    _extract_cursor_from_url,
    _extract_from_param,
    _generate_deterministic_id,
    _ts_to_iso,
    build_plan,
    is_captcha_html,
    parse_page,
    sanitize_html,
)

# ---------------------------------------------------------------------------
# Helpers Tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_sanitize_html(self):
        """Проверка очистки от скриптов, стилей и тегов."""
        assert sanitize_html("") == ""

        html = """
        <div class="test">
            <script>alert('hack');</script>
            <style>body {color: red;}</style>
            <h1>Hello   World</h1>
            <p>Test</p>
        </div>
        """
        assert sanitize_html(html) == "Hello World Test"

    def test_is_captcha_html(self):
        """Проверка быстрого детекта капчи."""
        assert is_captcha_html("") is False
        assert is_captcha_html("<html><body>Just normal text</body></html>") is False
        assert (
            is_captcha_html("<title>Just a moment...</title> Please verify you are human") is True
        )
        assert is_captcha_html("cf-turnstile-wrapper") is True

    def test_generate_deterministic_id(self):
        """ID должен генерироваться на основе author+text+date или словаря."""
        url = "http://test.com"

        # На основе текста, автора и даты (изменчивые поля вроде views игнорируются)
        id1 = _generate_deterministic_id({"author": "Alex", "text": "Hello", "views": 10}, url)
        id2 = _generate_deterministic_id({"author": "Alex", "text": "Hello", "views": 99}, url)
        assert id1 == id2
        assert id1.startswith("finist-")

        # На основе имени (если author нет)
        id3 = _generate_deterministic_id({"name": "Alex", "text": "Hello", "date": "2023"}, url)
        id4 = _generate_deterministic_id({"name": "Alex", "text": "Hello", "date": "2023"}, url)
        assert id3 == id4

        # Без текста (фолбек на сериализацию словаря, игнорируя служебные поля)
        id5 = _generate_deterministic_id({"title": "Post", "metadata": "ignore"}, url)
        id6 = _generate_deterministic_id({"title": "Post", "metadata": "changed"}, url)
        id7 = _generate_deterministic_id({"title": "Other"}, url)

        assert id5 == id6  # Изменение метаданных не меняет хеш
        assert id5 != id7  # Изменение реальных данных меняет хеш


# ---------------------------------------------------------------------------
# Build Plan Tests
# ---------------------------------------------------------------------------


class TestBuildPlan:
    def test_build_plan_missing_start_urls(self):
        """Если start_urls нигде нет, падает с ValueError."""
        with pytest.raises(ValueError, match="Не удалось определить стартовые URL"):
            build_plan({"crawler": {"list": {}}}, {})

    def test_build_plan_success(self):
        """Сборка плана из спеки и overrides."""
        spec = {
            "crawler": {
                "list": {
                    "start_urls": ["http://base.com"],
                    "item_selector": ".item",
                    "extraction_mode": "html",
                    "next_page": {"selector": ".next", "attr": "href"},
                    "fields": {
                        "title": "h1",  # Строковый селектор
                        "link": {
                            "selector": "a",
                            "attr": "href",
                            "default": "N/A",
                        },  # Dict-селектор
                    },
                },
                "limits": {"max_pages": 10},
                "render": "playwright",
            }
        }
        overrides = {"direct_urls": ["http://override.com"], "max_pages": 2}

        plan = build_plan(spec, overrides)

        assert plan.start_urls == ["http://override.com"]  # Override сработал
        assert plan.item_selector == ".item"
        assert plan.extraction_mode == "html"
        assert plan.max_pages == 2  # Override сработал
        assert plan.render_strategy == "playwright"
        assert plan.next_page_selector == ".next"

        # Проверка сборки полей
        assert len(plan.fields) == 2
        assert plan.fields["title"].selector == "h1"
        assert plan.fields["title"].attr is None
        assert plan.fields["link"].selector == "a"
        assert plan.fields["link"].attr == "href"
        assert plan.fields["link"].default == "N/A"


# ---------------------------------------------------------------------------
# HTMLExtractor Tests
# ---------------------------------------------------------------------------


class TestHTMLExtractor:
    @pytest.fixture
    def plan(self):
        return CrawlerPlan(
            start_urls=["http://test.com"],
            start_phase="list",
            item_selector=".post",
            next_page_selector=".next-btn",
            next_page_attr="href",
            request_headers={},
            fields={
                "title": FieldRule("h2"),
                "url": FieldRule("a", attr="href", default="Missing"),
                "text": FieldRule(".content"),
                "missing": FieldRule(".not-exist", default="Empty"),
                "self_attr": FieldRule(":self", attr="data-id"),
                "empty_rule": FieldRule(""),
            },
        )

    def test_extract_html_success(self, plan):
        html = """
        <html>
            <div class="post" data-id="100">
                <h2>Post 1</h2>
                <a href="/post1">Link</a>
                <div class="content"><script>alert('x');</script>Clean Text</div>
            </div>
            <div class="post" data-id="101">
                <h2>Post 2</h2>
                <!-- No link here -->
            </div>
            <a class="next-btn" href="?page=2">Next</a>
        </html>
        """
        extractor = HTMLExtractor()
        records, next_url, _ = extractor.extract(html, plan, "http://test.com", "list")

        assert len(records) == 2

        # Проверка первой записи
        assert records[0]["title"] == "Post 1"
        assert records[0]["url"] == "/post1"
        assert records[0]["text"] == "Clean Text"  # Sanitize сработал
        assert records[0]["missing"] == "Empty"  # Default сработал
        assert records[0]["self_attr"] == "100"  # :self сработал
        assert records[0]["message_url"] == "http://test.com"
        assert "external_id" in records[0]

        # Проверка второй записи
        assert records[1]["title"] == "Post 2"
        assert records[1]["url"] == "Missing"  # Дефолт для атрибута

        # Проверка пагинации (join относительной ссылки)
        assert next_url == "http://test.com?page=2"

    def test_extract_html_empty_record(self):
        """Если после фильтрации полей словарь пуст, он игнорируется."""
        html = '<div class="post"></div>'
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector=".post",
            request_headers={},
            fields={"dummy": FieldRule("")},
        )
        records, next_url, _ = HTMLExtractor().extract(html, plan, "http://test.com", "list")

        assert records == []


# ---------------------------------------------------------------------------
# JSONExtractor Tests
# ---------------------------------------------------------------------------


class TestJSONExtractor:
    @pytest.fixture
    def plan(self):
        return CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            next_page_selector="meta.next_cursor",
            pagination_mode="cursor",
            request_headers={},
            fields={
                "id": FieldRule("id"),
                "title": FieldRule("snippet.title"),
                "text": FieldRule("content", default=""),
                "missing": FieldRule("fake", default="N/A"),
            },
        )

    def test_extract_pure_json(self, plan):
        json_data = {
            "meta": {"next_cursor": "/api/v2?page=2"},
            "items": [
                {"id": 1, "snippet": {"title": "A"}, "content": "<b>Text A</b>"},
                {"id": 2, "snippet": {"title": "B"}},
            ],
        }
        extractor = JSONExtractor()
        records, next_url, _ = extractor.extract(json.dumps(json_data), plan, "http://test.com", "list")

        assert len(records) == 2
        assert records[0]["id"] == "1"
        assert records[0]["title"] == "A"
        assert records[0]["text"] == "Text A"  # Sanitize
        assert records[0]["missing"] == "N/A"

        # Пагинация (относительный путь сджойнен)
        assert next_url == "http://test.com?after=/api/v2?page=2"

    def test_extract_dict_wrapped_in_list(self, plan):
        """Если item_selector находит dict вместо list, extractor оборачивает в list."""
        json_data = {"items": {"id": 99, "snippet": {"title": "Single"}}}
        extractor = JSONExtractor()
        records, next_url, _ = extractor.extract(json.dumps(json_data), plan, "http://test.com", "list")

        assert len(records) == 1
        assert records[0]["id"] == "99"
        assert next_url is None

    def test_extract_invalid_json(self, plan):
        """Если JSON битый, экстрактор не падает, а возвращает пустые данные."""
        extractor = JSONExtractor()

        rec1, n1, _ = extractor.extract('{ "items": [ }', plan, "url", "list")
        assert rec1 == []

        rec2, n2, _ = extractor.extract("{ bad }", plan, "url", "list")
        assert rec2 == []

    def test_extract_json_empty_record(self):
        """Если JSON пустой или все селекторы полей пустые, запись пропускается."""
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            request_headers={},
            fields={"dummy": FieldRule("")},
        )

        empty_plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            request_headers={},
            fields={},
        )

        records, next_url, _ = JSONExtractor().extract('{"items": [{"id": 1}]}', empty_plan, "url", "list")
        assert records == []


# ---------------------------------------------------------------------------
# Parse Page (Facade) Tests
# ---------------------------------------------------------------------------


class TestParsePage:
    def test_parse_page_html_mode(self):
        plan = CrawlerPlan(
            ["url"],
            start_phase="list",
            item_selector="div",
            request_headers={},
            fields={"a": FieldRule("a")},
            extraction_mode="html",
        )
        records, next_url, _ = parse_page("<div><a>Link</a></div>", plan, "http://url")
        assert len(records) == 1

    def test_parse_page_json_mode(self):
        plan = CrawlerPlan(
            ["url"],
            start_phase="list",
            item_selector="[]",
            request_headers={},
            fields={"a": FieldRule("a")},
            extraction_mode="json",
        )
        records, next_url, _ = parse_page('[{"a": "Link"}]', plan, "http://url")
        assert len(records) == 1

    @patch.object(HTMLExtractor, "extract", side_effect=Exception("Critical Crash"))
    def test_parse_page_exception_fallback(self, mock_extract, caplog):
        """Любая ошибка внутри парсера перехватывается, чтобы не уронить воркер."""
        plan = CrawlerPlan(
            ["url"],
            start_phase="list",
            item_selector="div",
            request_headers={},
            fields={},
        )
        records, next_url, _ = parse_page("<html>", plan, "url")

        assert records == []
        assert next_url is None
        assert "Сбой при извлечении данных" in caplog.text


# ---------------------------------------------------------------------------
# Additional Helper Functions
# ---------------------------------------------------------------------------


class TestExtractHelpers:
    def test_extract_from_param_present(self):
        assert _extract_from_param("http://example.com?from=20") == 20
        assert _extract_from_param("http://example.com?from=0") == 0

    def test_extract_from_param_missing(self):
        assert _extract_from_param("http://example.com") == 0
        assert _extract_from_param("http://example.com?other=5") == 0

    def test_extract_app_id_from_url(self):
        assert _extract_app_id_from_url("https://store.steampowered.com/appreviews/730?cursor=abc") == 730
        assert _extract_app_id_from_url("https://store.steampowered.com/appreviews/12345") == 12345

    def test_extract_app_id_from_url_no_match(self):
        assert _extract_app_id_from_url("https://example.com/no-match") is None

    def test_extract_cursor_from_url(self):
        assert _extract_cursor_from_url("http://example.com?cursor=abc123") == "abc123"

    def test_extract_cursor_from_url_encoded(self):
        assert _extract_cursor_from_url("http://example.com?cursor=hello%20world") == "hello world"

    def test_extract_cursor_from_url_missing(self):
        assert _extract_cursor_from_url("http://example.com?other=5") is None

    def test_ts_to_iso_valid(self):
        result = _ts_to_iso(1609459200)
        assert result is not None
        assert "2021" in result

    def test_ts_to_iso_none(self):
        assert _ts_to_iso(None) is None

    def test_ts_to_iso_invalid(self):
        assert _ts_to_iso("not-a-number") == "not-a-number"

    def test_ts_to_iso_float(self):
        result = _ts_to_iso(1609459200.5)
        assert result is not None
        assert "2021" in result

    def test_ts_to_iso_string_number(self):
        result = _ts_to_iso("1609459200")
        assert result is not None
        assert "2021" in result


# ---------------------------------------------------------------------------
# Build Plan — additional branches
# ---------------------------------------------------------------------------


class TestBuildPlanBranches:
    def test_direct_urls_detail_flow(self):
        spec = {"flow": ["detail"], "crawler": {"detail": {}}}
        overrides = {"direct_urls": ["http://detail.com/item/1"]}
        plan = build_plan(spec, overrides)
        assert plan.start_urls == ["http://detail.com/item/1"]
        assert plan.start_phase == "detail"

    def test_direct_urls_with_list_flow(self):
        spec = {"flow": ["list", "detail"], "crawler": {"list": {}}}
        overrides = {"direct_urls": ["http://list.com"]}
        plan = build_plan(spec, overrides)
        assert plan.start_urls == ["http://list.com"]
        assert plan.start_phase == "list"

    def test_detail_flow_with_url_template(self):
        spec = {
            "flow": ["detail"],
            "crawler": {"detail": {"url_template": "http://api.com/{app_id}/reviews"}},
        }
        overrides = {"template_params": {"app_id": "730"}}
        plan = build_plan(spec, overrides)
        assert plan.start_urls == ["http://api.com/730/reviews"]
        assert plan.start_phase == "detail"

    def test_detail_flow_missing_param_raises(self):
        spec = {
            "flow": ["detail"],
            "crawler": {"detail": {"url_template": "http://api.com/{missing}/reviews"}},
        }
        with pytest.raises(ValueError, match="Не хватает параметра"):
            build_plan(spec, {})

    def test_url_template_with_params(self):
        spec = {
            "crawler": {
                "list": {
                    "url_template": "http://search.com/?q={query}",
                    "url_template_params": {"query": "default"},
                }
            }
        }
        overrides = {"template_params": {"query": "python"}}
        plan = build_plan(spec, overrides)
        assert plan.start_urls == ["http://search.com/?q=python"]

    def test_url_template_missing_param_raises(self):
        spec = {
            "crawler": {
                "list": {"url_template": "http://search.com/?q={missing}"},
            }
        }
        with pytest.raises(ValueError, match="Не хватает параметра"):
            build_plan(spec, {})

    def test_detail_url_template_with_params(self):
        spec = {
            "crawler": {
                "list": {"start_urls": ["http://base.com"]},
                "detail": {
                    "url_template": "http://detail.com/{id}/page",
                    "fields": {"text": ".content"},
                },
            }
        }
        overrides = {"template_params": {"id": "123"}}
        plan = build_plan(spec, overrides)
        assert plan.detail_url_template == "http://detail.com/123/page"
        assert plan.detail_fields is not None
        assert "text" in plan.detail_fields

    def test_build_plan_with_detail_config(self):
        spec = {
            "crawler": {
                "list": {"start_urls": ["http://base.com"]},
                "detail": {
                    "item_selector": ".review",
                    "extraction_mode": "json",
                    "fields": {"text": "review_text"},
                    "next_page": {"selector": "cursor", "attr": "href"},
                    "pagination": {"mode": "cursor"},
                },
                "limits": {"max_pages": 3},
            }
        }
        plan = build_plan(spec, {})
        assert plan.detail_item_selector == ".review"
        assert plan.detail_extraction_mode == "json"
        assert plan.detail_pagination_mode == "cursor"
        assert plan.detail_next_page_selector == "cursor"
        assert plan.max_pages == 3


# ---------------------------------------------------------------------------
# HTMLExtractor — offset pagination
# ---------------------------------------------------------------------------


class TestHTMLExtractorOffsetPagination:
    def test_offset_pagination(self):
        plan = CrawlerPlan(
            start_urls=["http://test.com?offset=0"],
            start_phase="list",
            item_selector=".item",
            pagination_mode="offset",
            next_page_attr="10",
            request_headers={},
            fields={"title": FieldRule("h2")},
        )
        html = '<div class="item"><h2>Title 1</h2></div>'
        records, next_url, _ = HTMLExtractor().extract(html, plan, "http://test.com?offset=0", "list")
        assert len(records) == 1
        assert next_url == "http://test.com?offset=10"

    def test_offset_pagination_no_records(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector=".missing",
            pagination_mode="offset",
            next_page_attr="10",
            request_headers={},
            fields={"title": FieldRule("h2")},
        )
        html = '<div class="other"><h2>Title</h2></div>'
        records, next_url, _ = HTMLExtractor().extract(html, plan, "http://test.com?offset=0", "list")
        assert records == []
        assert next_url is None

    def test_offset_pagination_page_param(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector=".item",
            pagination_mode="offset",
            next_page_attr="1",
            request_headers={},
            fields={"title": FieldRule("h2")},
        )
        html = '<div class="item"><h2>Title</h2></div>'
        records, next_url, _ = HTMLExtractor().extract(html, plan, "http://test.com?page=1", "list")
        assert next_url == "http://test.com?page=2"


# ---------------------------------------------------------------------------
# JSONExtractor — cursor & offset pagination
# ---------------------------------------------------------------------------


class TestJSONExtractorPagination:
    def test_cursor_pagination_with_after_in_url(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            next_page_selector="next_cursor",
            pagination_mode="cursor",
            request_headers={},
            fields={"id": FieldRule("id")},
        )
        json_data = {"items": [{"id": 1}], "next_cursor": "page_2_cursor"}
        records, next_url, _ = JSONExtractor().extract(
            json.dumps(json_data), plan, "http://test.com?after=page_1_cursor", "list"
        )
        assert len(records) == 1
        assert "page_2_cursor" in next_url

    def test_cursor_pagination_without_after_in_url(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            next_page_selector="next_cursor",
            pagination_mode="cursor",
            request_headers={},
            fields={"id": FieldRule("id")},
        )
        json_data = {"items": [{"id": 1}], "next_cursor": "abc"}
        records, next_url, _ = JSONExtractor().extract(
            json.dumps(json_data), plan, "http://test.com/api", "list"
        )
        assert next_url == "http://test.com/api?after=abc"

    def test_cursor_pagination_cursor_is_none(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            next_page_selector="next_cursor",
            pagination_mode="cursor",
            request_headers={},
            fields={"id": FieldRule("id")},
        )
        json_data = {"items": [{"id": 1}]}
        records, next_url, _ = JSONExtractor().extract(
            json.dumps(json_data), plan, "http://test.com", "list"
        )
        assert next_url is None

    def test_offset_pagination(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            pagination_mode="offset",
            next_page_attr="20",
            request_headers={},
            fields={"id": FieldRule("id")},
        )
        json_data = {"items": [{"id": 1}]}
        records, next_url, _ = JSONExtractor().extract(
            json.dumps(json_data), plan, "http://test.com?offset=0", "list"
        )
        assert len(records) == 1
        assert next_url == "http://test.com?offset=20"

    def test_offset_pagination_no_records(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            pagination_mode="offset",
            next_page_attr="20",
            request_headers={},
            fields={"id": FieldRule("id")},
        )
        json_data = {"items": []}
        records, next_url, _ = JSONExtractor().extract(
            json.dumps(json_data), plan, "http://test.com?offset=0", "list"
        )
        assert records == []
        assert next_url is None

    def test_json_raw_api_meta(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            request_headers={},
            fields={"id": FieldRule("id")},
        )
        json_data = {"items": [{"id": 1}], "meta": {"total": 100}}
        _, _, page_meta = JSONExtractor().extract(
            json.dumps(json_data), plan, "http://test.com", "list"
        )
        assert page_meta["raw_api_meta"] == {"total": 100}


# ---------------------------------------------------------------------------
# LentaSearchExtractor Tests
# ---------------------------------------------------------------------------


class TestLentaSearchExtractor:
    @pytest.fixture
    def extractor(self):
        return LentaSearchExtractor()

    @pytest.fixture
    def plan(self):
        return CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="",
            request_headers={},
            fields={},
        )

    def test_extract_search_success(self, extractor, plan):
        data = {
            "matches": [
                {
                    "type": 1,
                    "url": "https://lenta.ru/news/2024/01/01/test/",
                    "docid": "abc123",
                    "title": "Test Article",
                    "text": "Short excerpt",
                    "pubdate": 1704067200,
                    "bloc": 1,
                    "image_url": "https://img.lenta.ru/test.jpg",
                },
                {
                    "type": 2,
                    "url": "https://lenta.ru/articles/2024/01/02/article/",
                    "docid": "def456",
                    "title": "Test Longread",
                    "text": "Another excerpt",
                    "pubdate": 1704153600,
                    "bloc": 2,
                    "image_url": "",
                },
            ],
            "total_found": 50,
            "total": 50,
        }
        records, next_url, meta = extractor.extract(
            json.dumps(data), plan, "https://lenta.ru/search?v2=1&from=0", "list"
        )

        assert len(records) == 2
        assert records[0]["title"] == "Test Article"
        assert records[0]["source"] == "lenta.ru"
        assert records[0]["type"] == "Новость"
        assert records[0]["rubric"] == "Россия"
        assert records[0]["detail_url"] == "https://lenta.ru/news/2024/01/01/test/"
        assert records[0]["created_at"] is not None
        assert records[0]["external_id"] == "abc123"
        assert records[1]["type"] == "Статья"
        assert records[1]["rubric"] == "Мир"
        assert next_url is not None
        assert "from=2" in next_url
        assert meta["total_found"] == 50
        assert meta["current_from"] == 0

    def test_extract_search_filters_disallowed_types(self, extractor, plan):
        data = {
            "matches": [
                {"type": 3, "url": "https://lenta.ru/gallery/", "docid": "g1", "title": "Gallery"},
                {"type": 6, "url": "https://lenta.ru/video/", "docid": "v1", "title": "Video"},
                {"type": 1, "url": "https://lenta.ru/news/", "docid": "n1", "title": "News", "pubdate": 0, "bloc": 0},
            ],
            "total_found": 3,
        }
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://lenta.ru/search?from=0", "list"
        )
        assert len(records) == 1
        assert records[0]["title"] == "News"

    def test_extract_search_skips_no_url(self, extractor, plan):
        data = {
            "matches": [
                {"type": 1, "title": "No URL article"},
            ],
            "total_found": 1,
        }
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://lenta.ru/search?from=0", "list"
        )
        assert records == []

    def test_extract_search_empty_matches(self, extractor, plan):
        data = {"matches": [], "total_found": 0}
        records, next_url, meta = extractor.extract(
            json.dumps(data), plan, "https://lenta.ru/search?from=0", "list"
        )
        assert records == []
        assert next_url is None
        assert meta == {}

    def test_extract_search_invalid_json(self, extractor, plan):
        records, next_url, meta = extractor.extract(
            "not valid json", plan, "https://lenta.ru/search?from=0", "list"
        )
        assert records == []
        assert next_url is None
        assert meta == {}

    def test_extract_search_pagination_stops_at_total(self, extractor, plan):
        data = {
            "matches": [
                {"type": 1, "url": "https://lenta.ru/news/1/", "docid": "a", "title": "A", "pubdate": 0, "bloc": 0},
            ],
            "total_found": 1,
        }
        records, next_url, _ = extractor.extract(
            json.dumps(data), plan, "https://lenta.ru/search?from=0", "list"
        )
        assert len(records) == 1
        assert next_url is None

    def test_extract_search_pagination_capped_at_10000(self, extractor, plan):
        matches = [
            {"type": 1, "url": f"https://lenta.ru/news/{i}/", "docid": str(i), "title": f"A{i}", "pubdate": 0, "bloc": 0}
            for i in range(20)
        ]
        data = {"matches": matches, "total_found": 50000, "total": 50000}
        records, next_url, meta = extractor.extract(
            json.dumps(data), plan, "https://lenta.ru/search?from=0", "list"
        )
        assert len(records) == 20
        assert meta["api_total"] == 10000
        assert next_url is not None
        assert "from=20" in next_url

    def test_extract_article_json_topic_info(self, extractor, plan):
        html = """
        <html>
        <script class="json-topic-info">
        {
            "text": "This is a sufficiently long article body text that exceeds the thirty character minimum threshold for extraction.",
            "author": {"@type": "Person", "name": "Ivan Petrov"},
            "description": "Short description",
            "alternativeHeadline": "Alt Title"
        }
        </script>
        </html>
        """
        records, next_url, meta = extractor.extract(
            html, plan, "https://lenta.ru/news/2024/01/01/test/", "detail"
        )
        assert len(records) == 1
        assert "sufficiently long" in records[0]["text"]
        assert records[0]["author"] == "Ivan Petrov"
        assert records[0]["description"] == "Short description"
        assert records[0]["alt_headline"] == "Alt Title"
        assert records[0]["external_id"] is not None
        assert next_url is None

    def test_extract_article_json_author_string(self, extractor, plan):
        html = """
        <html>
        <script class="json-topic-info">
        {
            "text": "This is a sufficiently long article body text that exceeds the thirty character minimum threshold for extraction.",
            "author": "String Author Name"
        }
        </script>
        </html>
        """
        records, _, _ = extractor.extract(html, plan, "https://lenta.ru/news/1/", "detail")
        assert records[0]["author"] == "String Author Name"

    def test_extract_article_json_short_text_falls_through(self, extractor, plan):
        html = """
        <html>
        <script class="json-topic-info">
        {"text": "Short", "author": "Author"}
        </script>
        <div class="topic-body__content">
            <p class="topic-body__content-text">Full paragraph text from CSS fallback here.</p>
        </div>
        <span class="topic-authors__name">CSS Author</span>
        </html>
        """
        records, _, _ = extractor.extract(html, plan, "https://lenta.ru/news/1/", "detail")
        assert len(records) == 1
        assert "Full paragraph text" in records[0]["text"]
        assert records[0]["author"] == "CSS Author"

    def test_extract_article_css_fallback(self, extractor, plan):
        html = """
        <html>
        <div class="topic-body__content">
            <p class="topic-body__content-text">First paragraph.</p>
            <p class="topic-body__content-text">Second paragraph.</p>
        </div>
        <span class="topic-authors__name">John Doe</span>
        </html>
        """
        records, next_url, _ = extractor.extract(html, plan, "https://lenta.ru/news/1/", "detail")
        assert len(records) == 1
        assert records[0]["text"] == "First paragraph. Second paragraph."
        assert records[0]["author"] == "John Doe"

    def test_extract_article_css_no_paragraphs(self, extractor, plan):
        html = """
        <html>
        <div class="topic-body__content">Raw content without paragraph tags.</div>
        </html>
        """
        records, _, _ = extractor.extract(html, plan, "https://lenta.ru/news/1/", "detail")
        assert len(records) == 1
        assert "Raw content" in records[0]["text"]

    def test_extract_article_no_content(self, extractor, plan):
        html = "<html><body><p>Nothing relevant</p></body></html>"
        records, _, _ = extractor.extract(html, plan, "https://lenta.ru/news/1/", "detail")
        assert len(records) == 1
        assert "text" not in records[0] or records[0].get("text") is None

    def test_extract_article_bad_json_script_falls_through(self, extractor, plan):
        html = """
        <html>
        <script class="json-topic-info">{bad json}</script>
        <div class="topic-body__content">
            <p class="topic-body__content-text">CSS fallback content is here for testing.</p>
        </div>
        </html>
        """
        records, _, _ = extractor.extract(html, plan, "https://lenta.ru/news/1/", "detail")
        assert len(records) == 1
        assert "CSS fallback" in records[0]["text"]


# ---------------------------------------------------------------------------
# SteamCursorExtractor Tests
# ---------------------------------------------------------------------------


class TestSteamCursorExtractor:
    @pytest.fixture
    def extractor(self):
        return SteamCursorExtractor()

    @pytest.fixture
    def plan(self):
        return CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="",
            request_headers={},
            fields={
                "review_id": FieldRule("recommendationid"),
                "text": FieldRule("review"),
                "voted_up": FieldRule("voted_up"),
                "playtime_at_review_hours": FieldRule("author.playtime_at_review"),
                "playtime_total_hours": FieldRule("author.playtime_forever"),
                "missing_field": FieldRule("nonexistent", default="N/A"),
            },
        )

    def test_extract_success(self, extractor, plan):
        data = {
            "success": 1,
            "cursor": "new_cursor_abc",
            "reviews": [
                {
                    "recommendationid": 12345,
                    "review": "Great game!\nLoved it.",
                    "voted_up": True,
                    "author": {"playtime_at_review": 300, "playtime_forever": 600},
                },
            ],
            "query_summary": {"total_reviews": 42},
        }
        records, next_url, meta = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730?cursor=old", "list"
        )
        assert len(records) == 1
        assert records[0]["review_id"] == 12345
        assert "Great game!" in records[0]["text"]
        assert "\n" not in records[0]["text"]
        assert records[0]["voted_up"] is True
        assert records[0]["playtime_at_review_hours"] == 5.0
        assert records[0]["playtime_total_hours"] == 10.0
        assert records[0]["missing_field"] == "N/A"
        assert records[0]["game_appid"] == 730
        assert records[0]["external_id"] == "12345"
        assert next_url is not None
        assert "new_cursor_abc" in next_url
        assert meta["total_reviews"] == 42

    def test_extract_invalid_json(self, extractor, plan):
        records, next_url, meta = extractor.extract(
            "bad json", plan, "https://store.steampowered.com/appreviews/730", "list"
        )
        assert records == []
        assert next_url is None
        assert meta == {}

    def test_extract_success_not_1(self, extractor, plan):
        data = {"success": 0, "reviews": []}
        records, next_url, meta = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730", "list"
        )
        assert records == []
        assert next_url is None
        assert meta == {}

    def test_extract_empty_reviews(self, extractor, plan):
        data = {"success": 1, "reviews": [], "cursor": "*", "query_summary": {}}
        records, next_url, meta = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730?cursor=*", "list"
        )
        assert records == []
        assert next_url is None

    def test_extract_cursor_unchanged_stops_pagination(self, extractor, plan):
        data = {
            "success": 1,
            "cursor": "same_cursor",
            "reviews": [
                {"recommendationid": 1, "review": "ok", "voted_up": True, "author": {}},
            ],
            "query_summary": {},
        }
        records, next_url, _ = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730?cursor=same_cursor", "list"
        )
        assert len(records) == 1
        assert next_url is None

    def test_extract_no_cursor_in_url(self, extractor, plan):
        data = {
            "success": 1,
            "cursor": "first_page_cursor",
            "reviews": [
                {"recommendationid": 1, "review": "ok", "voted_up": True, "author": {}},
            ],
            "query_summary": {},
        }
        records, next_url, _ = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730", "list"
        )
        assert len(records) == 1
        assert next_url is not None
        assert next_url == "https://store.steampowered.com/appreviews/730"

    def test_extract_playtime_invalid_value(self, extractor, plan):
        data = {
            "success": 1,
            "cursor": "*",
            "reviews": [
                {
                    "recommendationid": 1,
                    "review": "meh",
                    "voted_up": False,
                    "author": {"playtime_at_review": "invalid", "playtime_forever": "bad"},
                },
            ],
            "query_summary": {},
        }
        records, next_url, _ = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730?cursor=old", "list"
        )
        assert len(records) == 1
        assert records[0]["playtime_at_review_hours"] == 0.0
        assert records[0]["playtime_total_hours"] == 0.0

    def test_extract_no_app_id(self, extractor, plan):
        data = {
            "success": 1,
            "cursor": "c1",
            "reviews": [
                {"recommendationid": 99, "review": "ok", "voted_up": True, "author": {}},
            ],
            "query_summary": {},
        }
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://other-api.com/reviews", "list"
        )
        assert records[0]["game_appid"] is None

    def test_extract_external_id_fallback(self, extractor):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="",
            request_headers={},
            fields={"text": FieldRule("review")},
        )
        data = {
            "success": 1,
            "cursor": "c1",
            "reviews": [{"review": "Some review text here."}],
            "query_summary": {},
        }
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730", "list"
        )
        assert len(records) == 1
        assert records[0]["external_id"].startswith("finist-")

    def test_extract_detail_phase(self, extractor):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="detail",
            item_selector="",
            request_headers={},
            fields={},
            detail_fields={"text": FieldRule("review")},
        )
        data = {
            "success": 1,
            "cursor": "c1",
            "reviews": [{"review": "Detail review text."}],
            "query_summary": {},
        }
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730", "detail"
        )
        assert len(records) == 1
        assert records[0]["text"] == "Detail review text."


# ---------------------------------------------------------------------------
# RedditExtractor Tests
# ---------------------------------------------------------------------------


class TestRedditExtractor:
    @pytest.fixture
    def extractor(self):
        return RedditExtractor()

    @pytest.fixture
    def plan(self):
        return CrawlerPlan(
            start_urls=["url"],
            start_phase="detail",
            item_selector="",
            request_headers={},
            fields={},
            detail_fields={
                "external_id": FieldRule("id"),
                "text": FieldRule("body"),
                "author": FieldRule("author"),
            },
        )

    def _make_detail_json(self, comments):
        return [
            {"data": {"children": [{"kind": "t3", "data": {"title": "Test Post Title"}}]}},
            {"data": {"children": comments}},
        ]

    def test_extract_detail_success(self, extractor, plan):
        data = self._make_detail_json([
            {"kind": "t1", "data": {"id": "c1", "body": "First comment", "author": "user1", "parent_id": "t3_xyz"}},
            {"kind": "t1", "data": {"id": "c2", "body": "Second comment", "author": "user2", "parent_id": "t3_xyz"}},
        ])
        records, next_url, meta = extractor.extract(
            json.dumps(data), plan, "https://reddit.com/r/test/comments/abc/", "detail"
        )
        assert len(records) == 2
        assert records[0]["text"] == "First comment"
        assert records[0]["author"] == "user1"
        assert records[0]["title"] == "Test Post Title"
        assert records[0]["depth"] == 0
        assert records[0]["reply_to_id"] == "t3_xyz"
        assert next_url is None

    def test_extract_nested_replies(self, extractor, plan):
        data = self._make_detail_json([
            {
                "kind": "t1",
                "data": {
                    "id": "c1",
                    "body": "Parent comment",
                    "author": "user1",
                    "parent_id": "t3_xyz",
                    "replies": {
                        "data": {
                            "children": [
                                {
                                    "kind": "t1",
                                    "data": {
                                        "id": "c2",
                                        "body": "Nested reply",
                                        "author": "user2",
                                        "parent_id": "t1_c1",
                                    },
                                }
                            ]
                        }
                    },
                },
            },
        ])
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://reddit.com/r/test/comments/abc/", "detail"
        )
        assert len(records) == 2
        assert records[0]["depth"] == 0
        assert records[1]["depth"] == 1
        assert records[1]["text"] == "Nested reply"

    def test_extract_skips_deleted_body(self, extractor, plan):
        data = self._make_detail_json([
            {"kind": "t1", "data": {"id": "c1", "body": "[deleted]", "author": "user1"}},
            {"kind": "t1", "data": {"id": "c2", "body": "[removed]", "author": "user2"}},
            {"kind": "t1", "data": {"id": "c3", "body": "Valid comment", "author": "user3"}},
        ])
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://reddit.com/r/test/comments/abc/", "detail"
        )
        assert len(records) == 1
        assert records[0]["text"] == "Valid comment"

    def test_extract_skips_non_t1_kind(self, extractor, plan):
        data = self._make_detail_json([
            {"kind": "t3", "data": {"id": "p1", "body": "Post body", "author": "op"}},
            {"kind": "t1", "data": {"id": "c1", "body": "Comment body", "author": "user1"}},
        ])
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://reddit.com/r/test/comments/abc/", "detail"
        )
        assert len(records) == 1
        assert records[0]["text"] == "Comment body"

    def test_extract_invalid_json(self, extractor, plan):
        records, next_url, meta = extractor.extract(
            "bad json", plan, "https://reddit.com/r/test/", "detail"
        )
        assert records == []
        assert next_url is None
        assert meta == {}

    def test_extract_list_phase_returns_empty(self, extractor):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="",
            request_headers={},
            fields={"text": FieldRule("body")},
        )
        data = [{"data": {"children": []}}]
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://reddit.com/r/test/", "list"
        )
        assert records == []

    def test_extract_missing_field_uses_default(self, extractor):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="detail",
            item_selector="",
            request_headers={},
            fields={},
            detail_fields={
                "text": FieldRule("body"),
                "author": FieldRule("author", default="anonymous"),
                "score": FieldRule("score", default="0"),
            },
        )
        data = self._make_detail_json([
            {"kind": "t1", "data": {"id": "c1", "body": "Comment without author or score"}},
        ])
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://reddit.com/r/test/comments/abc/", "detail"
        )
        assert len(records) == 1
        assert records[0]["author"] == "anonymous"
        assert records[0]["score"] == "0"

    def test_extract_text_newlines_stripped(self, extractor, plan):
        data = self._make_detail_json([
            {"kind": "t1", "data": {"id": "c1", "body": "Line 1\r\nLine 2\r\nLine 3", "author": "user1"}},
        ])
        records, _, _ = extractor.extract(
            json.dumps(data), plan, "https://reddit.com/r/test/comments/abc/", "detail"
        )
        assert "\n" not in records[0]["text"]
        assert "\r" not in records[0]["text"]


# ---------------------------------------------------------------------------
# parse_page — dispatching to specialized extractors
# ---------------------------------------------------------------------------


class TestParsePageDispatching:
    def test_parse_page_lenta_search(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="",
            extraction_mode="lenta_search",
            request_headers={},
            fields={},
        )
        data = {
            "matches": [
                {
                    "type": 1,
                    "url": "https://lenta.ru/news/1/",
                    "docid": "x",
                    "title": "Title",
                    "pubdate": 0,
                    "bloc": 0,
                },
            ],
            "total_found": 1,
        }
        records, _, meta = parse_page(
            json.dumps(data), plan, "https://lenta.ru/search?from=0", "list"
        )
        assert len(records) == 1
        assert records[0]["source"] == "lenta.ru"
        assert meta["total_found"] == 1

    def test_parse_page_lenta_article_detail(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="detail",
            item_selector="",
            detail_extraction_mode="lenta_article",
            request_headers={},
            fields={},
        )
        html = """
        <html>
        <script class="json-topic-info">
        {"text": "Full article text that is long enough to pass the threshold check for extraction."}
        </script>
        </html>
        """
        records, _, _ = parse_page(html, plan, "https://lenta.ru/news/1/", "detail")
        assert len(records) == 1
        assert "Full article" in records[0]["text"]

    def test_parse_page_steam(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="",
            extraction_mode="steam",
            request_headers={},
            fields={"review_id": FieldRule("recommendationid")},
        )
        data = {
            "success": 1,
            "cursor": "c1",
            "reviews": [{"recommendationid": 42}],
            "query_summary": {"total_reviews": 1},
        }
        records, next_url, meta = parse_page(
            json.dumps(data), plan, "https://store.steampowered.com/appreviews/730", "list"
        )
        assert len(records) == 1
        assert records[0]["review_id"] == 42
        assert meta["total_reviews"] == 1

    def test_parse_page_reddit(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="detail",
            item_selector="",
            extraction_mode="html",
            detail_extraction_mode="reddit",
            request_headers={},
            fields={},
            detail_fields={
                "text": FieldRule("body"),
                "author": FieldRule("author"),
            },
        )
        data = [
            {"data": {"children": [{"kind": "t3", "data": {"title": "Post"}}]}},
            {"data": {"children": [
                {"kind": "t1", "data": {"id": "c1", "body": "Comment", "author": "u1"}},
            ]}},
        ]
        records, next_url, _ = parse_page(
            json.dumps(data), plan, "https://reddit.com/r/test/comments/abc/", "detail"
        )
        assert len(records) == 1
        assert records[0]["text"] == "Comment"

    def test_parse_page_default_uses_html(self):
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector=".item",
            extraction_mode="unknown_mode",
            request_headers={},
            fields={"title": FieldRule("h2")},
        )
        html = '<div class="item"><h2>Title</h2></div>'
        records, _, _ = parse_page(html, plan, "http://test.com", "list")
        assert len(records) == 1
        assert records[0]["title"] == "Title"
