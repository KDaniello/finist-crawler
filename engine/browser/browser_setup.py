"""
ImmortalBrowser — long-lived stealth browser session.
Адаптировано для Finist Crawler (Camoufox 0.4.11+).
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar

from browserforge.fingerprints import Screen
from camoufox.async_api import AsyncCamoufox
from playwright.async_api import BrowserContext, Page, Route

from .behaviors import HumanBehavior

logger = logging.getLogger(__name__)

__all__ = ["LEAN_PREFS", "ImmortalBrowser"]

LEAN_PREFS = {
    # Ограничиваем процессы
    "dom.ipc.processCount": 1,
    "dom.ipc.processCount.webIsolated": 1,
    "dom.ipc.processCount.extension": 0,
    "dom.ipc.processCount.file": 0,
    # Отключаем изоляцию сайтов (Fission)
    "fission.autostart": False,
    "fission.webContentIsolationStrategy": 0,
    # Пытаемся полностью отключить мультипроцессность (e10s)
    "browser.tabs.remote.autostart": False,
    "browser.tabs.remote.autostart.2": False,
    "extensions.e10sBlocksEnabling": True,
    # Рубим GPU и медиа
    "layers.gpu-process.enabled": False,
    "layers.gpu-process.force-enabled": False,
    "gfx.e10s.multi.gpu": False,
    "media.rdd-process.enabled": False,
    "media.utility-process.enabled": False,
    "network.process.enabled": False,
    # Отключаем воркеры и телеметрию
    "dom.serviceWorkers.enabled": False,
    "toolkit.telemetry.enabled": False,
    "datareporting.policy.dataSubmissionEnabled": False,
    # Жесткая экономия кэша
    "javascript.options.mem.high_water_mark": 32,
    "browser.cache.memory.capacity": 16384,
    "browser.cache.disk.enable": False,
}


def _extract_context(camoufox_result: Any, profile_dir: Path) -> BrowserContext:
    """
    Универсальный экстрактор BrowserContext из любого объекта, который возвращает Camoufox.

    Camoufox менял API между версиями. Эта функция обрабатывает все варианты:
    - BrowserContext напрямую (новые версии с persistent context)
    - Browser объект (старые версии, нужно достать контекст)

    Raises:
        RuntimeError: Если не удалось распознать тип объекта.
    """
    obj_type = type(camoufox_result).__name__
    logger.debug(f"[browser] Camoufox вернул объект типа: {obj_type}")

    # ВАРИАНТ 1: Объект уже является BrowserContext (имеет .pages и .new_page)
    # Это поведение Camoufox когда он запускается с persistent_context=True
    if hasattr(camoufox_result, "pages") and hasattr(camoufox_result, "new_page"):
        logger.debug("[browser] Получен BrowserContext напрямую")
        return camoufox_result  # type: ignore

    # ВАРИАНТ 2: Объект является Browser (имеет .contexts и .new_context)
    # Нужно создать или достать BrowserContext из него
    if hasattr(camoufox_result, "contexts"):
        logger.debug("[browser] Получен Browser, извлекаем BrowserContext")
        browser = camoufox_result

        if browser.contexts:
            # Берем первый существующий контекст
            return browser.contexts[0]  # type: ignore

        # Контекстов нет — создаем новый persistent
        # Используем asyncio в синхронном контексте — этот метод вызывается из async, так что ok
        raise RuntimeError(
            "[browser] Browser вернул пустой список контекстов. "
            "Используйте _extract_context только из async-кода через await."
        )

    # ВАРИАНТ 3: Объект является Playwright (имеет .firefox)
    # Это старое поведение AsyncCamoufox
    if hasattr(camoufox_result, "firefox"):
        logger.debug("[browser] Получен Playwright объект (старый API)")
        raise RuntimeError(
            "[browser] Получен Playwright объект напрямую. "
            "Используй _start_via_playwright() для этого случая."
        )

    raise RuntimeError(
        f"[browser] Неизвестный тип объекта от Camoufox: {obj_type}. "
        f"Доступные атрибуты: {[a for a in dir(camoufox_result) if not a.startswith('_')]}"
    )


class ImmortalBrowser:
    """Менеджер жизненного цикла браузера Camoufox для конкретного домена."""

    _DEFAULT_BLOCKED_DOMAINS: ClassVar[list[str]] = [
        "google-analytics.com",
        "doubleclick.net",
        "facebook.net",
        "facebook.com",
        "mc.yandex.ru",
        "hotjar.com",
        "tiktok.com",
        "metrika.yandex.ru",
        "sentry.io",
        "googletagmanager.com",
    ]

    def __init__(
        self,
        domain: str,
        profiles_dir: Path,
        headless: bool = False,
        proxy_url: str | None = None,
        block_media: bool = True,
        block_trackers: bool = True,
        apply_lean_prefs: bool = False,
        browser_factory: Callable[..., AsyncCamoufox] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> None:
        self.domain = domain
        self.profiles_dir = profiles_dir
        self.headless = headless
        self.proxy_url = proxy_url
        self.block_media = block_media
        self.block_trackers = block_trackers
        self.apply_lean_prefs = apply_lean_prefs

        self._browser_factory = browser_factory
        self._blocked_domains = (
            blocked_domains if blocked_domains is not None else list(self._DEFAULT_BLOCKED_DOMAINS)
        )

        self._cm: AsyncCamoufox | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._behavior: HumanBehavior | None = None
        self._started_at: float | None = None

    async def start(self) -> Page:
        profile_dir = self.profiles_dir / self.domain
        profile_dir.mkdir(parents=True, exist_ok=True)

        custom_prefs = LEAN_PREFS.copy() if self.apply_lean_prefs else {}
        if self.block_media:
            custom_prefs["permissions.default.image"] = 2
        else:
            custom_prefs["permissions.default.image"] = 1

        screen_fp = Screen(min_width=1920, max_width=1920, min_height=1080, max_height=1080)

        # --- ФИКС: Делаем браузер максимально человечным ---
        kwargs: dict[str, Any] = {
            "headless": self.headless,
            "humanize": True,
            "firefox_user_prefs": custom_prefs,
            "persistent_context": True,
            "user_data_dir": str(profile_dir),
            "screen": screen_fp,
        }

        if self.proxy_url:
            kwargs["proxy"] = {"server": self.proxy_url}

        proxy_info = "proxy=YES" if self.proxy_url else "proxy=NO"
        logger.info(
            f"[browser] starting | domain={self.domain} profile={profile_dir.name} {proxy_info}"
        )

        factory = self._browser_factory or AsyncCamoufox
        self._cm = factory(**kwargs)  # type: ignore[no-untyped-call]

        # AsyncCamoufox.__aenter__ возвращает разные типы в зависимости от версии и конфига.
        # _extract_context() определяет тип и возвращает нам гарантированный BrowserContext.
        raw_result = await self._cm.__aenter__()

        # Обрабатываем случай, когда нам вернули Browser вместо BrowserContext
        if hasattr(raw_result, "contexts"):
            # Это Browser объект — создаем persistent context через стандартный Playwright API
            browser = raw_result

            # Пробуем через launch_persistent_context если есть доступ к BrowserType
            if hasattr(browser, "new_context"):
                if browser.contexts:
                    self._context = browser.contexts[0]
                else:
                    self._context = await browser.new_context()
            else:
                raise RuntimeError(f"[browser] Не удалось создать контекст из {type(browser)}")

        elif hasattr(raw_result, "pages") and hasattr(raw_result, "new_page"):
            # Это уже BrowserContext — отлично, берем напрямую
            self._context = raw_result

        elif hasattr(raw_result, "firefox"):
            # Это Playwright объект (старый API Camoufox)
            # Создаём persistent context через firefox.launch_persistent_context
            playwright = raw_result
            self._context = await playwright.firefox.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self.headless,
                firefox_user_prefs=custom_prefs,
                **({"proxy": {"server": self.proxy_url}} if self.proxy_url else {}),
            )

        else:
            # Последний шанс: логируем всё что знаем и падаем с понятной ошибкой
            attrs = [a for a in dir(raw_result) if not a.startswith("_")]
            raise RuntimeError(
                f"[browser] Неизвестный объект от AsyncCamoufox.__aenter__(): "
                f"type={type(raw_result).__name__}, attrs={attrs}"
            )

        if self._context is None:
            raise RuntimeError("[browser] Не удалось создать BrowserContext")

        # Достаём или создаём страницу
        if self._context.pages:
            self._page = self._context.pages[0]
            logger.debug("[browser] reused existing page from profile")
        else:
            self._page = await self._context.new_page()
            logger.debug("[browser] created new page")

        self._behavior = HumanBehavior(self._page)

        if self.block_media or self.block_trackers:
            await self._setup_network_interception()

        self._started_at = time.time()
        logger.info(f"[browser] ready | domain={self.domain} | LEAN_PREFS applied!")

        return self._page

    async def stop(
        self,
        exc_type: type | None = None,
        exc_value: BaseException | None = None,
        traceback: object | None = None,
    ) -> None:
        logger.info(f"[browser] stopping | domain={self.domain} uptime={self.uptime:.0f}s")

        if self._page and not self._page.is_closed():
            with contextlib.suppress(Exception):
                await self._page.close()

        # Закрываем persistent context (сохраняет куки на диск автоматически)
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as exc:
                logger.warning(f"[browser] error closing context: {exc}")

        # Закрываем Playwright/Camoufox
        if self._cm is not None:
            try:
                await self._cm.__aexit__(exc_type, exc_value, traceback)
            except Exception as exc:
                logger.warning(f"[browser] error during shutdown: {exc}")
            finally:
                self._cm = None
                self._context = None
                self._page = None
                self._behavior = None

    async def restart(self) -> Page:
        await self.stop()
        return await self.start()

    async def new_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("Browser not started")
        return await self._context.new_page()

    async def __aenter__(self) -> ImmortalBrowser:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.stop(exc_type, exc_value, traceback)

    async def _setup_network_interception(self) -> None:
        if not self._context:
            return

        allowed_types = {"document", "script", "xhr", "fetch"}
        blocked_domains = self._blocked_domains

        async def route_handler(route: Route) -> None:
            req = route.request

            if self.block_media and req.resource_type not in allowed_types:
                await route.abort("aborted")
                return

            if self.block_trackers and any(domain in req.url for domain in blocked_domains):
                await route.abort("aborted")
                return

            await route.continue_()

        await self._context.route("**/*", route_handler)
        logger.debug(
            "[BENCHMARK] Browser: Network Interception АКТИВЕН (Whitelist: doc, script, xhr)"
        )

    @property
    def uptime(self) -> float:
        return time.time() - self._started_at if self._started_at else 0.0

    @property
    def page(self) -> Page | None:
        return self._page

    @property
    def context(self) -> BrowserContext | None:
        return self._context

    @property
    def is_alive(self) -> bool:
        if self._page is None:
            return False
        try:
            closed = self._page.is_closed()
            return not (closed() if callable(closed) else closed)
        except Exception:
            return False

    @property
    def behavior(self) -> HumanBehavior | None:
        return self._behavior

    def __repr__(self) -> str:
        status = "alive" if self.is_alive else "stopped"
        return f"<ImmortalBrowser domain={self.domain} {status} uptime={self.uptime:.0f}s>"
