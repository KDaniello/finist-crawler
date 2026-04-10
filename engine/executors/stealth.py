import asyncio
import logging
from collections import defaultdict, deque
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError

from core.exceptions import CaptchaBlockError
from engine.browser.browser_setup import ImmortalBrowser
from engine.parsing_rules import CrawlerPlan, is_captcha_html, parse_page
from engine.rate_limiter import DomainConfig, TokenBucket

from .base import ExecutorStats, SaveCallback

logger = logging.getLogger(__name__)

__all__ = ["StealthExecutor"]


class StealthExecutor:
    @property
    def name(self) -> str:
        return "StealthExecutor (Camoufox)"

    def __init__(self, browser_lock, profiles_dir: str) -> None:
        self._browser_lock = browser_lock
        self._profiles_dir = profiles_dir
        self._max_retries = 2

    async def __aenter__(self) -> "StealthExecutor":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def execute(
        self, plan: CrawlerPlan, save_cb: SaveCallback, proxy_url: str | None = None
    ) -> tuple[int, ExecutorStats]:
        domain = urlparse(plan.start_urls[0]).netloc

        bucket = TokenBucket(
            DomainConfig(
                requests_per_second=plan.requests_per_second,
                burst_size=1,
                adaptive=False,
            )
        )

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
        total_records = 0
        current_list_page = 1
        branch_stats: dict[str, dict[str, int | None]] = defaultdict(
            lambda: {"current": 0, "total": None}
        )

        logger.info(f"[{self.name}] Ожидание системной блокировки браузера...")
        await asyncio.to_thread(self._browser_lock.acquire)

        try:
            from pathlib import Path

            p_dir = Path(self._profiles_dir)
            p_dir.mkdir(parents=True, exist_ok=True)

            async with ImmortalBrowser(
                domain=domain,
                profiles_dir=p_dir,
                headless=False,
                proxy_url=proxy_url,
                block_media=False,
                block_trackers=False,
                apply_lean_prefs=False,
            ) as browser:
                logger.info(f"[{self.name}] Браузер запущен. Начинаем обход.")

                while (list_queue and list_pages_crawled < plan.max_pages) or detail_queue:
                    if list_queue and list_pages_crawled < plan.max_pages:
                        url, phase, retries = list_queue.popleft()
                        if phase == "list":
                            logger.info(f"TELEMETRY|PAGE_START|{current_list_page}")
                            current_list_page += 1
                    elif detail_queue:
                        url, phase, retries = detail_queue.popleft()
                    else:
                        break

                    if url in visited:
                        continue

                    await bucket.acquire()

                    try:
                        if browser.page is None:
                            raise PlaywrightError("Page is None")

                        logger.debug(f"[{self.name}] Открываю: {url}")

                        resp = await browser.page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=plan.request_timeout_sec * 1000,
                        )

                        if resp and resp.status == 429:
                            bucket.report_rate_limited()
                            delay = 3**retries
                            logger.warning(f"[{self.name}] HTTP 429 на {url}. Ждем {delay}с...")
                            await asyncio.sleep(delay)
                            if retries < self._max_retries:
                                (detail_queue if phase == "detail" else list_queue).appendleft(
                                    (url, phase, retries + 1)
                                )
                            continue

                        # ФИКС: Ждем 3 секунды, чтобы скрипт Yandex SmartCaptcha успел отрисовать "Вы робот?"
                        await browser.page.wait_for_timeout(3000)
                        html = await browser.page.content()

                        # Проверяем, вылезла ли капча
                        is_blocked = (
                            is_captcha_html(html)
                            or "qrator" in html.lower()
                            or "вы робот" in html.lower()
                        )

                        wait_selector = (
                            ".item[itemprop='review'], .review-article" if phase == "list" else "h1"
                        )

                        if is_blocked:
                            logger.warning(f"[{self.name}] 🛡️ Капча! Ожидание решения (300 сек)...")
                            solved = False

                            # ЗАПУСКАЕМ ТАЙМЕР В ДАШБОРДЕ
                            for sec in range(300, 0, -1):
                                logger.info(f"TELEMETRY|CAPTCHA|WAITING|{sec}")
                                try:
                                    # Каждую секунду проверяем, не прогрузился ли уже контент Отзовика
                                    element = await browser.page.query_selector(wait_selector)
                                    if element and await element.is_visible():
                                        solved = True
                                        break
                                except Exception:
                                    pass
                                await asyncio.sleep(1)

                            if not solved:
                                raise CaptchaBlockError(
                                    url=url, detail="Таймаут 300 секунд истек. Капча не решена."
                                )

                            logger.info("TELEMETRY|CAPTCHA|SOLVED")
                            logger.info(f"[{self.name}] ✅ Капча решена! Продолжаем парсинг...")
                            await browser.page.wait_for_timeout(2000)

                        else:
                            # Быстрый путь, если капчи нет
                            try:
                                await browser.page.wait_for_selector(wait_selector, timeout=8000)
                            except Exception:
                                pass

                        # Забираем итоговый HTML
                        html = await browser.page.content()
                        bucket.report_success()

                        records, next_url, page_meta = parse_page(
                            html=html, plan=plan, page_url=url, phase=phase
                        )

                        if phase == "list":
                            is_two_stage = bool(plan.detail_fields)
                            if is_two_stage:
                                for r in records:
                                    d_url = r.get("detail_url")
                                    if d_url:
                                        if plan.detail_url_template:
                                            d_url = plan.detail_url_template.replace(
                                                "{}", str(d_url)
                                            )
                                        if d_url not in enqueued:
                                            detail_queue.append((d_url, "detail", 0))
                                            enqueued.add(d_url)
                            else:
                                if records:
                                    save_cb(records)
                                    total_records += len(records)

                            list_pages_crawled += 1
                            if next_url and next_url not in visited and next_url not in enqueued:
                                list_queue.append((next_url, "list", 0))
                                enqueued.add(next_url)

                        elif phase == "detail":
                            if records:
                                save_cb(records)
                                total_records += len(records)

                            base_url = url.split("?")[0]
                            branch_stats[base_url]["current"] += len(records)
                            current = branch_stats[base_url]["current"]

                            logger.info(f"TELEMETRY|PROGRESS|{base_url}|{current}|-1")

                            if next_url and next_url not in visited and next_url not in enqueued:
                                detail_queue.append((next_url, "detail", 0))
                                enqueued.add(next_url)
                            elif not next_url:
                                logger.info(f"TELEMETRY|BRANCH_DONE|{base_url}|{current}")

                        visited.add(url)

                    except CaptchaBlockError as e:
                        logger.error(f"[{self.name}] Капча не решена: {e}")
                        break
                    except PlaywrightError as e:
                        logger.warning(f"[{self.name}] Ошибка Playwright на {url}: {e}")
                        if retries < self._max_retries:
                            (detail_queue if phase == "detail" else list_queue).appendleft(
                                (url, phase, retries + 1)
                            )
                    except Exception as e:
                        logger.error(f"[{self.name}] Неизвестный сбой на {url}: {e}", exc_info=True)
                        break

        finally:
            self._browser_lock.release()

        stats: ExecutorStats = {
            "executor": self.name,
            "pages_crawled": len(visited),
            "records_found": total_records,
        }
        return total_records, stats
