import logging

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

logger = logging.getLogger(__name__)

__all__ = ["is_captcha_page"]

# Комплексный JS-скрипт для быстрого детектирования всех популярных защит.
# Выполняется атомарно внутри V8/SpiderMonkey.
_CAPTCHA_DETECT_JS = """
() => {
    // 1. Проверка по явным селекторам iframe/контейнеров капчи
    const sels = [
        'iframe[src*="recaptcha"]',
        'iframe[src*="hcaptcha"]',
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[src*="turnstile"]',
        'iframe[src*="datadome"]',
        '.g-recaptcha',
        '.h-captcha',
        '#captcha',
        '[data-sitekey]',
        '.cf-turnstile',
        '#cf-challenge-running',
        '#challenge-running'
    ];
    for (const s of sels) {
        if (document.querySelector(s)) return true;
    }

    // 2. Проверка заголовка (Title) страницы (самый надежный способ для Cloudflare)
    const title = (document.title || '').toLowerCase();
    if (title.includes('just a moment') || title.includes('attention required') || title.includes('security measure')) {
        return true;
    }

    // 3. Проверка текста страницы (ограничиваем поиск первыми 5000 символами)
    // Используем documentElement, чтобы захватить текст даже если body еще не отрендерился полностью
    const t = (document.documentElement?.innerText || '').substring(0, 5000).toLowerCase();

    const markers = [
        'checking your browser before accessing',
        'verify you are human',
        'are you a robot',
        'please verify that you are a human',
        'checking if the site connection is secure',
        'enable javascript and cookies to continue' // DataDome/Cloudflare fallback
    ];

    for (const m of markers) {
        if (t.includes(m)) return true;
    }

    return false;
}
"""


async def is_captcha_page(page: Page) -> bool:
    """
    Выполняет один атомарный JS-запрос к странице для выявления
    Cloudflare, ReCaptcha, hCaptcha, Turnstile и DataDome.

    Returns:
        bool: True, если обнаружена защита.
    """
    try:
        # Пытаемся оценить скрипт без ожидания полной загрузки (это быстрее)
        result = await page.evaluate(_CAPTCHA_DETECT_JS)
        return bool(result)
    except PlaywrightError as e:
        # Если страница закрылась во время оценки или контекст уничтожен
        logger.debug(f"is_captcha_page: Ошибка Playwright при оценке JS: {e}")
        return False
    except Exception as e:
        logger.debug(f"is_captcha_page: Неожиданная ошибка: {e}")
        return False
