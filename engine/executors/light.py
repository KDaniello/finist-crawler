import asyncio
import logging
import random
from collections import defaultdict, deque
from types import TracebackType
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.errors import RequestsError

from core.exceptions import CaptchaBlockError
from engine.parsing_rules import CrawlerPlan, is_captcha_html, parse_page
from engine.rate_limiter import DomainConfig, TokenBucket

from .base import ExecutorStats, SaveCallback

logger = logging.getLogger(__name__)

__all__ = ["LightExecutor"]

_IMPERSONATES = ["chrome131", "chrome124", "chrome120"]


class LightExecutor:
    @property
    def name(self) -> str:
        return "LightExecutor (curl_cffi)"

    def __init__(
        self, impersonate: str | None = "chrome120", request_timeout: float = 30.0
    ) -> None:
        self._preferred_impersonate = impersonate
        self._request_timeout = request_timeout
        self._client: AsyncSession | None = None
        self._max_retries = 4

    async def __aenter__(self) -> "LightExecutor":
        impersonate = (
            self._preferred_impersonate
            if self._preferred_impersonate is not None
            else random.choice(_IMPERSONATES)
        )

        base_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }

        kwargs = {
            "timeout": self._request_timeout,
            "allow_redirects": True,
            "headers": base_headers,
        }

        if impersonate:
            kwargs["impersonate"] = impersonate

        self._client = AsyncSession(**kwargs)  # type: ignore[arg-type]
        await self._client.__aenter__()  # type: ignore[no-untyped-call]

        logger.info(f"[LightExecutor] Запущен с impersonate={impersonate}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None

    async def execute(
        self, plan: CrawlerPlan, save_cb: SaveCallback, proxy_url: str | None = None
    ) -> tuple[int, ExecutorStats]:
        if not self._client:
            raise RuntimeError("Context Manager required.")

        domain = urlparse(plan.start_urls[0]).netloc

        bucket = TokenBucket(
            DomainConfig(
                requests_per_second=plan.requests_per_second,
                burst_size=plan.concurrency,
                adaptive=True,
            )
        )

        if getattr(plan, "warmup_urls", None) or getattr(plan, "rotate_fingerprint", True):
            await self._warmup(domain, getattr(plan, "warmup_urls", None))

        list_queue: deque[tuple[str, str, int]] = deque()
        detail_queue: deque[tuple[str, str, int]] = deque()

        for url in plan.start_urls:
            if plan.start_phase == "detail":
                detail_queue.append((url, "detail", 0))
            else:
                list_queue.append((url, "list", 0))

        visited: set[str] = set()
        enqueued: set[str] = set(plan.start_urls)

        list_pages_crawled = 0
        detail_pages_crawled = 0
        total_records = 0
        current_list_page = 1
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        branch_stats: dict[str, dict[str, int | None]] = defaultdict(
            lambda: {"current": 0, "total": None}
        )

        # 0 = без ограничений (для 2GIS, Habr — все detail-страницы собираются целиком)
        detail_limit = plan.detail_max_pages

        logger.info(
            f"[{self.name}] Старт парсинга {domain} | impersonate={self._client.impersonate} "
            f"| Proxy: {'Да' if proxy_url else 'Нет'} "
            f"| detail_max_pages={detail_limit if detail_limit > 0 else '∞'}"
        )

        async def fetch_and_process(url: str, phase: str, retries: int) -> None:
            nonlocal total_records, detail_pages_crawled

            await bucket.acquire()
            try:
                headers = plan.request_headers or None
                if headers and random.random() < 0.3:
                    headers = headers.copy()
                    headers.setdefault(
                        "Accept",
                        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    )

                resp = await self._client.get(url, proxies=proxies, headers=headers)  # type: ignore[union-attr, arg-type]

                if resp.status_code == 429:
                    bucket.report_rate_limited()
                    delay = 2**retries * 1.5
                    logger.warning(f"[RateLimit] 429 на {domain}. Пауза {delay:.1f} сек...")
                    await asyncio.sleep(delay)
                    if retries < self._max_retries:
                        (detail_queue if phase == "detail" else list_queue).append(
                            (url, phase, retries + 1)
                        )
                    return

                if resp.status_code in (403, 503) or is_captcha_html(resp.text):
                    raise CaptchaBlockError(
                        url=url,
                        detail=f"HTTP {resp.status_code} / Captcha (body len: {len(resp.text)})",
                    )

                if resp.status_code >= 500:
                    if retries < self._max_retries:
                        await asyncio.sleep(1.5)
                        (detail_queue if phase == "detail" else list_queue).append(
                            (url, phase, retries + 1)
                        )
                    return

                if resp.status_code >= 400:
                    logger.warning(f"HTTP {resp.status_code} на {url}")
                    return

                bucket.report_success()
                records, next_url, page_meta = parse_page(
                    html=resp.text, plan=plan, page_url=url, phase=phase
                )

                if phase == "list":
                    is_two_stage = bool(plan.detail_fields)
                    if is_two_stage:
                        for r in records:
                            d_url = r.get("detail_url")
                            if d_url:
                                if plan.detail_url_template:
                                    d_url = plan.detail_url_template.replace("{}", str(d_url))
                                if d_url not in enqueued:
                                    detail_queue.append((d_url, "detail", 0))
                                    enqueued.add(d_url)
                    else:
                        if records:
                            save_cb(records)
                            total_records += len(records)

                    if next_url and next_url not in visited and next_url not in enqueued:
                        list_queue.append((next_url, "list", 0))
                        enqueued.add(next_url)

                elif phase == "detail":
                    if records:
                        save_cb(records)
                        total_records += len(records)

                    # Считаем каждую успешно обработанную detail-страницу
                    detail_pages_crawled += 1

                    base_url = url.split("?")[0]
                    branch_stats[base_url]["current"] = (branch_stats[base_url]["current"] or 0) + len(records)

                    current = branch_stats[base_url]["current"] or 0

                    # Определяем total для прогресс-бара.
                    # Для Steam НЕ берём total_reviews из API — там общее число
                    # отзывов за всё время (сотни тысяч), что делает прогресс-бар
                    # бесполезным. Вместо этого считаем от detail_max_pages.
                    if detail_limit > 0:
                        # Знаем точный лимит страниц → считаем максимум записей
                        records_per_page = len(records) if records else 50
                        total_for_ui: int | None = detail_limit * records_per_page
                    else:
                        # Двухэтапный парсер (2GIS, Habr) — берём из API
                        api_meta = page_meta.get("raw_api_meta", {})
                        expected = api_meta.get("branch_reviews_count") or api_meta.get(
                            "total_count"
                        )
                        if expected is not None:
                            branch_stats[base_url]["total"] = expected
                        total_for_ui = branch_stats[base_url]["total"]

                    logger.info(f"TELEMETRY|PROGRESS|{base_url}|{current}|{total_for_ui or -1}")

                    # Проверяем лимит перед добавлением следующей страницы
                    detail_limit_reached = detail_limit > 0 and detail_pages_crawled >= detail_limit

                    if detail_limit_reached:
                        # Лимит достигнут — сигнализируем UI и не добавляем next_url
                        logger.info(f"TELEMETRY|BRANCH_DONE|{base_url}|{current}")
                    elif total_for_ui is None or current < total_for_ui:
                        if next_url and next_url not in visited and next_url not in enqueued:
                            detail_queue.append((next_url, "detail", 0))
                            enqueued.add(next_url)
                        elif not next_url:
                            logger.info(f"TELEMETRY|BRANCH_DONE|{base_url}|{current}")
                    else:
                        logger.info(f"TELEMETRY|BRANCH_DONE|{base_url}|{current}")

                visited.add(url)

            except CaptchaBlockError:
                raise
            except RequestsError as e:
                if retries < self._max_retries:
                    (detail_queue if phase == "detail" else list_queue).append(
                        (url, phase, retries + 1)
                    )
                else:
                    logger.error(f"Сетевая ошибка после {self._max_retries} попыток: {url} | {e}")
            except Exception as e:
                logger.error(f"Сбой парсинга {url}: {e}", exc_info=True)

        # Основной цикл с учётом detail_max_pages
        while True:
            detail_limit_reached = detail_limit > 0 and detail_pages_crawled >= detail_limit
            has_list = bool(list_queue) and list_pages_crawled < plan.max_pages
            has_detail = bool(detail_queue) and not detail_limit_reached

            if not has_list and not has_detail:
                break

            batch_tasks: list[tuple[str, str, int]] = []

            while len(batch_tasks) < plan.concurrency:
                detail_limit_reached = detail_limit > 0 and detail_pages_crawled >= detail_limit

                if detail_queue and not detail_limit_reached:
                    batch_tasks.append(detail_queue.popleft())
                elif list_queue and list_pages_crawled < plan.max_pages:
                    url, phase, retries = list_queue.popleft()
                    if phase == "list":
                        logger.info(f"TELEMETRY|PAGE_START|{current_list_page}")
                        current_list_page += 1
                        list_pages_crawled += 1
                    batch_tasks.append((url, phase, retries))
                else:
                    break

            if not batch_tasks:
                break

            await asyncio.gather(*(fetch_and_process(u, p, r) for u, p, r in batch_tasks))

        stats: ExecutorStats = {
            "executor": self.name,
            "pages_crawled": len(visited),
            "detail_pages_crawled": detail_pages_crawled,
            "records_found": total_records,
        }
        return total_records, stats

    async def _warmup(self, domain: str, extra_warmup_urls: list[str] | None = None) -> None:
        """Прогрев сессии — помогает против Cloudflare/Reddit."""
        urls = [f"https://{domain}"]
        if extra_warmup_urls:
            urls.extend(extra_warmup_urls[:2])

        for url in urls:
            try:
                await asyncio.sleep(random.uniform(0.7, 2.1))
                await self._client.get(url, timeout=12.0)  # type: ignore[union-attr]
                logger.debug(f"[Warmup] Успешный запрос на {url}")
            except Exception as e:
                logger.debug(f"[Warmup] Не удалось прогреться на {url}: {e}")
