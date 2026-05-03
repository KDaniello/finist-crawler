"""
Тесты для engine/browser/detection.py

Покрытие: 100%
- is_captcha_page:
    - Возврат True/False из JS-скрипта.
    - Перехват ошибки PlaywrightError (страница закрыта/контекст уничтожен).
    - Перехват любых неожиданных ошибок (Exception fallback).
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest


class FakePlaywrightError(Exception):
    pass


import engine.browser.detection
from engine.browser.detection import _CAPTCHA_DETECT_JS, is_captcha_page


@pytest.fixture(autouse=True)
def _patch_playwright_error():
    original = engine.browser.detection.PlaywrightError
    engine.browser.detection.PlaywrightError = FakePlaywrightError
    yield
    engine.browser.detection.PlaywrightError = original

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_page():
    """Мокает объект Page из Playwright."""
    page = MagicMock()
    page.evaluate = AsyncMock()
    return page


# ---------------------------------------------------------------------------
# is_captcha_page Tests
# ---------------------------------------------------------------------------


class TestIsCaptchaPage:
    @pytest.mark.asyncio
    async def test_returns_true_when_captcha_detected(self, mock_page):
        """Если скрипт вернул истинное значение, функция возвращает True."""
        mock_page.evaluate.return_value = True

        result = await is_captcha_page(mock_page)

        assert result is True
        mock_page.evaluate.assert_called_once_with(_CAPTCHA_DETECT_JS)

    @pytest.mark.asyncio
    async def test_returns_false_when_no_captcha(self, mock_page):
        """Если скрипт вернул ложное значение (или None), функция возвращает False."""
        mock_page.evaluate.return_value = False

        result = await is_captcha_page(mock_page)

        assert result is False
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_playwright_error_gracefully(self, mock_page, caplog):
        """При ошибке IPC с браузером (например, вкладка закрыта) возвращается False."""
        # Используем нашу фейковую ошибку, чтобы Python понял, что это Exception
        mock_page.evaluate.side_effect = FakePlaywrightError("Target closed")

        with caplog.at_level(logging.DEBUG):
            result = await is_captcha_page(mock_page)

        assert result is False
        assert "Ошибка Playwright при оценке JS: Target closed" in caplog.text

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception_gracefully(self, mock_page, caplog):
        """При любой другой ошибке питона возвращается False."""
        mock_page.evaluate.side_effect = ValueError("Something went completely wrong")

        with caplog.at_level(logging.DEBUG):
            result = await is_captcha_page(mock_page)

        assert result is False
        assert "Неожиданная ошибка: Something went completely wrong" in caplog.text
