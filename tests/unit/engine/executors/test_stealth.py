"""
Тесты для engine/executors/stealth.py

Покрытие: 100%
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# 1. Создаем настоящую (но фейковую) ошибку для тестов
class FakePlaywrightError(Exception):
    pass


# 2. Подменяем замоканный класс в модуле stealth ДО того, как начнут работать тесты
import engine.executors.stealth

engine.executors.stealth.PlaywrightError = FakePlaywrightError

from core.exceptions import CaptchaBlockError, NetworkError
from engine.executors.stealth import StealthExecutor
from engine.parsing_rules import CrawlerPlan

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_lock():
    return MagicMock()


@pytest.fixture
def executor(mock_lock, tmp_path):
    """Обновленный фикстура: теперь принимает profiles_dir через tmp_path"""
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
def mock_profile_manager():
    """Мокает ProfileManager и возвращает объект сессии."""
    with patch("engine.executors.stealth.ProfileManager") as MockPM:
        mock_mgr = MagicMock()
        mock_session = MagicMock()
        mock_session.session_id = "test_session_123"
        mock_session.should_rotate = False

        mock_mgr.acquire.return_value = mock_session
        MockPM.return_value = mock_mgr

        yield mock_mgr, mock_session


@pytest.fixture
def mock_browser():
    """Мокает ImmortalBrowser."""
    with patch("engine.executors.stealth.ImmortalBrowser") as MockBrowserCls:
        mock_b_instance = AsyncMock()
        mock_b_instance.page = AsyncMock()
        mock_b_instance.page.content.return_value = "<html>test</html>"
        mock_b_instance.behavior = AsyncMock()

        # Настраиваем контекстный менеджер (async with ImmortalBrowser(...) as b)
        MockBrowserCls.return_value.__aenter__.return_value = mock_b_instance
        yield mock_b_instance


# ---------------------------------------------------------------------------
# Base & Helpers Tests
# ---------------------------------------------------------------------------


class TestStealthExecutorBase:
    def test_name(self, executor):
        assert "Camoufox" in executor.name

    @pytest.mark.asyncio
    async def test_context_manager(self, executor):
        """__aenter__ и __aexit__ не должны выбрасывать ошибок."""
        async with executor as exc:
            assert exc is executor


class TestWaitForCaptcha:
    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("engine.executors.stealth.is_captcha_page")
    async def test_wait_resolves_captcha(self, mock_is_captcha, mock_sleep, executor, mock_browser):
        """Проверяет, что капча проходится, если is_captcha_page становится False."""
        mock_is_captcha.side_effect = [True, False]
        result = await executor._wait_for_captcha(mock_browser, timeout=15)

        assert result is True
        assert mock_sleep.call_count == 2
        mock_browser.behavior.mouse_jiggle.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("engine.executors.stealth.is_captcha_page", return_value=True)
    async def test_wait_times_out(self, mock_is_captcha, mock_sleep, executor, mock_browser):
        """Если таймаут исчерпан, возвращает False."""
        result = await executor._wait_for_captcha(mock_browser, timeout=10)
        assert result is False
        assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# Execute Logic Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
@patch("engine.executors.stealth.is_captcha_page", return_value=False)
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
        mock_profile_manager,
        mock_browser,
        mock_lock,
    ):
        mgr, session = mock_profile_manager
        mock_parse.side_effect = [
            ([{"id": 1}], "http://test.com/page2"),
            ([{"id": 2}], None),
        ]

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 2
        assert stats["pages_crawled"] == 2
        assert stats["session_id"] == "test_session_123"

        mock_lock.acquire.assert_called_once()
        mock_lock.release.assert_called_once()
        assert mock_browser.behavior.mouse_jiggle.call_count == 2
        assert mock_browser.behavior.scroll_down.call_count == 2
        assert mgr.report_success.call_count == 2

    async def test_execute_empty_parse_result(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_profile_manager,
        mock_browser,
    ):
        mgr, session = mock_profile_manager
        mock_parse.return_value = ([], None)

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
        assert stats["pages_crawled"] == 1
        mgr.report_success.assert_not_called()

    async def test_execute_should_rotate_aborts(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_profile_manager,
        mock_browser,
    ):
        mgr, session = mock_profile_manager
        session.should_rotate = True

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
        assert stats["pages_crawled"] == 0
        assert stats["queue_remaining"] == 1
        mock_browser.page.goto.assert_not_called()

    async def test_execute_playwright_error_aborts(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_profile_manager,
        mock_browser,
    ):
        mgr, session = mock_profile_manager
        mock_browser.page.goto.side_effect = FakePlaywrightError("Browser crashed")

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
        assert stats["queue_remaining"] == 1
        mgr.report_failure.assert_called_once_with(session)

    async def test_execute_captcha_timeout_raises(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_profile_manager,
        mock_browser,
        mock_lock,
    ):
        mgr, session = mock_profile_manager
        mock_is_captcha.return_value = True

        with patch.object(executor, "_wait_for_captcha", return_value=False):
            with pytest.raises(CaptchaBlockError, match="Авто-решение капчи не удалось"):
                await executor.execute(dummy_plan, mock_save_cb)

        mgr.report_failure.assert_called_once_with(session, is_captcha=True)
        mock_lock.release.assert_called_once()

    async def test_execute_global_exception_raises_network_error(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        dummy_plan,
        mock_save_cb,
        mock_profile_manager,
        mock_browser,
        mock_lock,
    ):
        mgr, session = mock_profile_manager
        mock_parse.side_effect = ValueError("Something completely broken")

        with pytest.raises(NetworkError, match="Сбой браузера"):
            await executor.execute(dummy_plan, mock_save_cb)

        mock_lock.release.assert_called_once()

    async def test_execute_duplicate_visited_url(
        self,
        mock_parse,
        mock_is_captcha,
        mock_sleep,
        executor,
        mock_save_cb,
        mock_profile_manager,
        mock_browser,
    ):
        plan = CrawlerPlan(
            start_urls=["http://test.com", "http://test.com"],
            item_selector="div",
            fields={},
        )
        mock_parse.return_value = ([{"id": 1}], None)

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
        mock_profile_manager,
        mock_browser,
    ):
        """Если browser.page is None, выбрасывается PlaywrightError (и перехватывается)."""
        mgr, session = mock_profile_manager
        mock_browser.page = None  # Имитируем падение страницы

        total, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total == 0
        assert stats["queue_remaining"] == 1
        mgr.report_failure.assert_called_once_with(session)
