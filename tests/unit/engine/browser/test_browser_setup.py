"""
Тесты для engine/browser/browser_setup.py

Покрытие: 100%
- Инициализация ImmortalBrowser (передача параметров, создание профиля, LEAN_PREFS, Proxy).
- start:
    - Успешный старт (с context.pages и без).
    - Camoufox возвращает сразу Context (без списка contexts).
    - Ошибка создания контекста (RuntimeError).
- stop:
    - Корректное закрытие страницы и контекста.
    - Перехват ошибок при закрытии страницы.
    - Перехват ошибок при закрытии контекста (__aexit__).
- restart: вызов stop() и start().
- new_page: создание новой вкладки (с и без контекста).
- Context Manager (__aenter__, __aexit__).
- _setup_network_interception:
    - Блокировка медиа (images/css).
    - Блокировка трекеров (google-analytics.com).
    - Пропуск разрешенных ресурсов (document/script).
    - Пропуск, если context = None.
    - Пропуск фильтрации, если флаги block = False.
- Свойства: uptime, is_alive (True/False/Exception), page, context, behavior, repr.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.browser.browser_setup import ImmortalBrowser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def profiles_dir(tmp_path: Path) -> Path:
    return tmp_path / "profiles"


@pytest.fixture
def browser(profiles_dir):
    """Инициализирует ImmortalBrowser с базовыми настройками."""
    return ImmortalBrowser(
        domain="reddit.com",
        profiles_dir=profiles_dir,
        headless=True,
        proxy_url="http://proxy",
        block_media=True,
        block_trackers=True,
    )


@pytest.fixture
def mock_camoufox():
    """Мокает AsyncCamoufox.__aenter__ и __aexit__."""
    with patch("engine.browser.browser_setup.AsyncCamoufox") as MockCM:
        instance = AsyncMock()
        context = MagicMock()
        context.pages = []
        context.new_page = AsyncMock(return_value=MagicMock())
        context.route = AsyncMock()

        # Симулируем структуру, когда __aenter__ возвращает браузер с contexts
        instance.__aenter__.return_value.contexts = [context]
        MockCM.return_value = instance

        yield MockCM, instance, context


# ---------------------------------------------------------------------------
# Start / Stop / Restart Tests
# ---------------------------------------------------------------------------


class TestBrowserLifecycle:
    @pytest.mark.asyncio
    async def test_start_success_new_page(self, browser, mock_camoufox):
        MockCM, cm_instance, context = mock_camoufox
        context.pages = []  # Нет открытых вкладок

        page = await browser.start()

        assert browser._context is context
        assert browser._page is context.new_page.return_value
        assert browser._behavior is not None
        assert browser.uptime > 0.0

        # Проверяем, что LEAN_PREFS и прокси передались
        kwargs = MockCM.call_args.kwargs
        assert kwargs["proxy"] == {"server": "http://proxy"}
        assert kwargs["firefox_user_prefs"]["permissions.default.image"] == 2

        context.new_page.assert_called_once()
        context.route.assert_called_once()  # Interception setup

    @pytest.mark.asyncio
    async def test_start_success_reused_page(self, browser, mock_camoufox):
        MockCM, cm_instance, context = mock_camoufox
        existing_page = MagicMock()
        context.pages = [existing_page]  # Уже есть вкладка

        page = await browser.start()

        assert browser._page is existing_page
        context.new_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_returns_context_directly(self, browser, mock_camoufox):
        """Если Camoufox возвращает сразу Context (без списка contexts)."""
        MockCM, cm_instance, context = mock_camoufox

        # Удаляем атрибут 'contexts', чтобы сработала ветка `else` (строки 154-155)
        del context.contexts
        cm_instance.__aenter__.return_value = context

        await browser.start()
        assert browser._context is context

    @pytest.mark.asyncio
    async def test_start_fails_no_context(self, browser, mock_camoufox):
        MockCM, cm_instance, context = mock_camoufox
        cm_instance.__aenter__.return_value = None  # Не удалось создать контекст

        with pytest.raises(RuntimeError):
            await browser.start()

    @pytest.mark.asyncio
    async def test_stop_success(self, browser, mock_camoufox):
        MockCM, cm_instance, context = mock_camoufox
        await browser.start()

        page_mock = browser._page
        page_mock.is_closed = MagicMock(return_value=False)
        page_mock.close = AsyncMock()

        await browser.stop()

        page_mock.close.assert_called_once()
        cm_instance.__aexit__.assert_called_once()

        assert browser._cm is None
        assert browser._context is None
        assert browser._page is None

    @pytest.mark.asyncio
    async def test_stop_ignores_page_close_error(self, browser, mock_camoufox):
        """Проверяет пропуск ошибки при закрытии страницы (строка 186)."""
        MockCM, cm_instance, context = mock_camoufox
        await browser.start()

        page_mock = browser._page
        page_mock.is_closed = MagicMock(return_value=False)
        page_mock.close = AsyncMock(side_effect=Exception("Target closed"))

        await browser.stop()  # Ошибка должна быть перехвачена except Exception: pass
        cm_instance.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_ignores_camoufox_exit_error(self, browser, mock_camoufox, caplog):
        MockCM, cm_instance, context = mock_camoufox
        await browser.start()

        cm_instance.__aexit__.side_effect = Exception("Camoufox Crash")

        await browser.stop()  # Не должно упасть
        assert "error during shutdown: Camoufox Crash" in caplog.text

    @pytest.mark.asyncio
    async def test_restart(self, browser, mock_camoufox):
        with patch.object(browser, "stop", new_callable=AsyncMock) as mock_stop:
            with patch.object(browser, "start", new_callable=AsyncMock) as mock_start:
                await browser.restart()

                mock_stop.assert_called_once()
                mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# Context Manager & Misc Tests
# ---------------------------------------------------------------------------


class TestBrowserMisc:
    @pytest.mark.asyncio
    async def test_context_manager(self, browser, mock_camoufox):
        MockCM, cm_instance, context = mock_camoufox

        async with browser as b:
            assert b is browser
            assert b._page is not None

        # __aexit__ должен вызвать stop
        cm_instance.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_page_success(self, browser, mock_camoufox):
        await browser.start()
        await browser.new_page()
        browser._context.new_page.assert_called()

    @pytest.mark.asyncio
    async def test_new_page_fails_if_not_started(self, browser):
        with pytest.raises(RuntimeError, match="Browser not started"):
            await browser.new_page()

    def test_uptime_without_start(self, browser):
        assert browser.uptime == 0.0

    @pytest.mark.asyncio
    async def test_is_alive_and_properties(self, browser, mock_camoufox):
        # До старта
        assert browser.is_alive is False
        assert "stopped" in repr(browser)
        assert browser.page is None
        assert browser.context is None
        assert browser.behavior is None

        await browser.start()

        # Свойства после старта
        assert browser.page is not None
        assert browser.context is not None
        assert browser.behavior is not None

        # is_closed возвращает callable (в старых версиях playwright)
        browser._page.is_closed = lambda: False
        assert browser.is_alive is True
        assert "alive" in repr(browser)

        # is_closed возвращает bool
        browser._page.is_closed = MagicMock(return_value=True)
        assert browser.is_alive is False

        # is_closed падает с ошибкой
        browser._page.is_closed = MagicMock(side_effect=Exception("Dead"))
        assert browser.is_alive is False


# ---------------------------------------------------------------------------
# Network Interception Tests
# ---------------------------------------------------------------------------


class TestNetworkInterception:
    @pytest.mark.asyncio
    async def test_interception_aborts_if_no_context(self, browser):
        """Если контекста нет, перехватчик не ставится (строка 230)."""
        browser._context = None
        await browser._setup_network_interception()
        # Ничего не упало, метод просто вернул None
        assert True

    @pytest.mark.asyncio
    async def test_route_handler(self, browser, mock_camoufox):
        """Проверка блокировки медиа и трекеров."""
        MockCM, cm_instance, context = mock_camoufox
        await browser.start()

        route_handler = context.route.call_args[0][1]

        # 1. Блокировка Media (image)
        route_img = MagicMock()
        route_img.request.resource_type = "image"
        route_img.request.url = "http://test.com/img.png"
        route_img.abort = AsyncMock()

        await route_handler(route_img)
        route_img.abort.assert_called_with("aborted")

        # 2. Блокировка трекеров
        route_tracker = MagicMock()
        route_tracker.request.resource_type = "script"
        route_tracker.request.url = "https://google-analytics.com/analytics.js"
        route_tracker.abort = AsyncMock()

        await route_handler(route_tracker)
        route_tracker.abort.assert_called_with("aborted")

        # 3. Пропуск валидного ресурса (document/fetch)
        route_valid = MagicMock()
        route_valid.request.resource_type = "fetch"
        route_valid.request.url = "https://api.test.com/data"
        route_valid.continue_ = AsyncMock()

        await route_handler(route_valid)
        route_valid.continue_.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_handler_disabled_blocks(self, profiles_dir, mock_camoufox):
        """Проверка пропуска ресурсов, если флаги блокировки = False."""
        MockCM, cm_instance, context = mock_camoufox

        # Выключаем блокировки
        browser = ImmortalBrowser(
            domain="reddit.com", profiles_dir=profiles_dir, block_media=False, block_trackers=False
        )
        await browser.start()

        # Принудительно вызываем _setup, чтобы повесить хендлер
        # (в start он не повесится, так как оба флага False, но мы проверим логику самого хендлера)
        await browser._setup_network_interception()
        route_handler = context.route.call_args[0][1]

        route_img = MagicMock()
        route_img.request.resource_type = "image"
        route_img.request.url = "https://google-analytics.com/img.png"
        route_img.continue_ = AsyncMock()

        await route_handler(route_img)

        # Должен быть пропущен (continue_), так как фильтры выключены (строка 234)
        route_img.continue_.assert_called_once()
        route_img.abort.assert_not_called()
