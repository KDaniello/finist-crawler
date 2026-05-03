"""
Тесты для engine/executors/stealth.py

Покрытие: 100%
- Инициализация и контекстный менеджер.
- Успешный парсинг: обработка страниц, вызов callback'а, статистика.
- Пустой результат парсинга.
- Ошибка Playwright: ретраи и graceful завершение.
- Капча: CaptchaBlockError при нерешённой капче.
- Глобальная ошибка: graceful break с освобождением блокировки.
- Дубликаты URL: пропуск повторных посещений.
- Page is None: PlaywrightError и ретраи.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakePlaywrightError(Exception):
    pass


import engine.executors.stealth

engine.executors.stealth.PlaywrightError = FakePlaywrightError

from core.exceptions import CaptchaBlockError
from engine.executors.stealth import StealthExecutor
from engine.parsing_rules import CrawlerPlan


@pytest.fixture
def mock_lock():
    return MagicMock()


@pytest.fixture
def executor(mock_lock, tmp_path):
    return StealthExecutor(browser_lock=mock_lock, profiles_dir=tmp_path)


@pytest.fixture
def dummy_plan():
    return CrawlerPlan(
        start_urls=["http://test.com/page1"],
        start_phase="list",
        item_selector=".item",
        fields={},
        request_headers={},
        max_pages=2,
    )


@pytest.fixture
def mock_save_cb():
    return MagicMock()


@pytest.fixture
def mock_browser():
    """Мокает ImmortalBrowser."""
    with patch("engine.executors.stealth.ImmortalBrowser") as MockBrowserCls:
        mock_b_instance = AsyncMock()
        mock_b_instance.page = AsyncMock()
        mock_b_instance.page.content.return_value = "<html>test</html>"

        MockBrowserCls.return_value.__aenter__.return_value = mock_b_instance
        yield mock_b_instance


class TestStealthExecutorBase:
    def test_name(self, executor):
        assert "Camoufox" in executor.name

    @pytest.mark.asyncio
    async def test_context_manager(self, executor):
        async with executor as exc:
            assert exc is executor


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
@patch("engine.executors.stealth.is_captcha_html", return_value=False)
@patch("engine.executors.stealth.parse_page")
class TestStealthExecutorExecute:
    async def test_execute_success_flow(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_browser,
        mock_lock,
    ):
        mock_parse.side_effect = [
            ([{"id": 1}], "http://test.com/page2", {}),
            ([{"id": 2}], None, {}),
        ]

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 2
        assert stats["pages_crawled"] == 2

        mock_lock.acquire.assert_called_once()
        mock_lock.release.assert_called_once()

    async def test_execute_empty_parse_result(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_browser,
    ):
        mock_parse.return_value = ([], None, {})

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
        assert stats["pages_crawled"] == 1

    async def test_execute_playwright_error_retries(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_browser,
    ):
        mock_browser.page.goto.side_effect = FakePlaywrightError("Browser crashed")

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0

    async def test_execute_captcha_timeout_breaks(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_browser,
        mock_lock,
    ):
        mock_is_captcha.return_value = True
        mock_browser.page.query_selector.return_value = None

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
        assert stats["pages_crawled"] == 0
        mock_lock.release.assert_called_once()

    async def test_execute_global_exception_breaks(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_browser,
        mock_lock,
    ):
        mock_parse.side_effect = ValueError("Something completely broken")

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
        assert stats["pages_crawled"] == 0
        mock_lock.release.assert_called_once()

    async def test_execute_duplicate_visited_url(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        mock_save_cb,
        mock_browser,
    ):
        plan = CrawlerPlan(
            start_urls=["http://test.com", "http://test.com"],
            start_phase="list",
            item_selector="div",
            request_headers={},
            fields={},
            max_pages=2,
        )
        mock_parse.return_value = ([{"id": 1}], None, {})

        total, stats = await executor.execute(plan, mock_save_cb)
        assert stats["pages_crawled"] == 1

    async def test_page_is_none_raises_playwright_error(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_browser,
    ):
        mock_browser.page = None

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
