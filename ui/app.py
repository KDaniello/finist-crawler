from __future__ import annotations

import logging
import multiprocessing
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import flet as ft

from core import get_paths, get_settings, setup_environment
from core._openpyxl_compat import apply_openpyxl_compat
from core.dispatcher import Dispatcher
from core.file_manager import SessionManager
from core.logger import LogManager
from core.resources import SystemMonitor
from ui.theme import ThemeController

logger = logging.getLogger(__name__)


def _resolve_font(relative_path: str) -> str:
    """
    Возвращает путь к шрифту для Flet.

    Приоритет:
    1. PyInstaller _MEIPASS (собранный .exe)
    2. Локальный файл assets/fonts/ (dev-режим со скачанными шрифтами)
    3. Google Fonts URL (dev-режим без шрифтов, требует интернет)
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent

    font_path = base / relative_path
    if font_path.exists():
        return str(font_path)

    _fallback_urls: dict[str, str] = {
        "assets/fonts/Inter-Regular.ttf": (
            "https://fonts.gstatic.com/s/inter/v13/"
            "UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hiJ-Ek-_EeA.woff2"
        ),
        "assets/fonts/JetBrainsMono-Regular.ttf": (
            "https://fonts.gstatic.com/s/jetbrainsmono/v18/"
            "tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjPVmUsaaDhw.woff2"
        ),
    }
    return _fallback_urls.get(relative_path, relative_path)


class AppController:
    """
    Центральный контроллер приложения.
    Связывает UI (Flet страницы) с бизнес-логикой.
    Не содержит UI-кода — только управление состоянием.
    """

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._paths = get_paths()
        self._settings = get_settings()

        apply_openpyxl_compat()

        self.log_manager = LogManager()
        self._log_queue = self.log_manager.setup(
            logs_dir=self._paths.logs_dir,
            debug=self._settings.DEBUG,
        )
        self.session_manager = SessionManager(base_dir=self._paths.data_dir)
        self.dispatcher = Dispatcher(
            session_manager=self.session_manager,
            log_queue=self._log_queue,
        )
        self.monitor = SystemMonitor()

        is_dark = page.platform_brightness != ft.Brightness.LIGHT
        self.theme = ThemeController(is_dark=is_dark)

        self.current_session_id: str | None = None
        self.active_specs: list[str] = []

        self.navigate: Callable[[str], None] = lambda route: None
        self._ui_log_handler: logging.Handler | None = None

    def start_parsing(self, job_configs: list[Any]) -> bool:
        from bots.universal_bot import run_universal_bot

        if self.dispatcher.is_running():
            logger.warning("Парсинг уже запущен")
            return False

        if not job_configs:
            return False

        specs = [cfg.spec_name for cfg in job_configs]
        overrides = job_configs[0].to_dict()

        session_id = self.dispatcher.start_tasks(
            worker_target=run_universal_bot,
            specs=specs,
            config_overrides=overrides,
        )

        if session_id:
            self.current_session_id = session_id
            self.active_specs = specs
            return True
        return False

    def stop_parsing(self) -> None:
        self.dispatcher.stop_all()

    def is_running(self) -> bool:
        return self.dispatcher.is_running()

    def cleanup(self) -> None:
        self.stop_parsing()
        self.log_manager.stop()
        self._log_queue.close()
        self._log_queue.cancel_join_thread()


class _PlaceholderPage:
    def __init__(self, title: str) -> None:
        self._title = title

    def build(self) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(self._title, size=24),
                    ft.Text("В разработке...", size=14),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
            alignment=ft.alignment.center,
        )


def _build_nav_bar(
    active_route: str,
    navigate: Callable[[str], None],
    ctrl: AppController,
    on_theme_toggle: Callable[[], None],
) -> ft.Container:
    """Строит верхнюю навигационную панель."""
    t = ctrl.theme.tokens

    nav_items = [
        ("launcher", "Запуск"),
        ("monitor", "Мониторинг"),
        ("results", "Результаты"),
    ]

    nav_buttons = []
    for route, label in nav_items:
        is_active = route == active_route
        nav_buttons.append(
            ft.Container(
                content=ft.Text(
                    label,
                    size=14,
                    weight=ft.FontWeight.W_500,
                    color=t.text_primary if is_active else t.text_secondary,
                    font_family="Inter",
                ),
                padding=ft.padding.symmetric(horizontal=16, vertical=8),
                border_radius=8,
                bgcolor=t.bg_elevated if is_active else "transparent",
                border=ft.border.all(1, t.border) if is_active else None,
                on_click=lambda e, r=route: navigate(r),
                ink=True,
            )
        )

    theme_icon = ft.IconButton(
        icon=ft.Icons.DARK_MODE if ctrl.theme.is_dark else ft.Icons.LIGHT_MODE,
        icon_color=t.text_secondary,
        icon_size=18,
        tooltip="Переключить тему",
        on_click=lambda e: on_theme_toggle(),
        style=ft.ButtonStyle(
            overlay_color=ft.Colors.with_opacity(0.08, t.accent),
        ),
    )

    is_running = ctrl.is_running()
    status_dot = ft.Container(
        width=8,
        height=8,
        border_radius=4,
        bgcolor=t.accent if is_running else t.text_muted,
    )
    status_label = ft.Text(
        "Активен" if is_running else "Ожидание",
        size=12,
        color=t.accent if is_running else t.text_muted,
        font_family="Inter",
    )

    return ft.Container(
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(
                                "F",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=t.accent,
                                font_family="Inter",
                            ),
                            width=32,
                            height=32,
                            border_radius=8,
                            bgcolor=ft.Colors.with_opacity(0.12, t.accent),
                            alignment=ft.Alignment(0, 0),
                        ),
                        ft.Text(
                            "Finist Crawler",
                            size=16,
                            weight=ft.FontWeight.W_600,
                            color=t.text_primary,
                            font_family="Inter",
                        ),
                    ],
                    spacing=10,
                ),
                ft.Row(controls=nav_buttons, spacing=4),
                ft.Row(
                    [
                        ft.Row([status_dot, status_label], spacing=6),
                        ft.Container(width=1, height=20, bgcolor=t.border),
                        theme_icon,
                    ],
                    spacing=12,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=t.bg_secondary,
        padding=ft.padding.symmetric(horizontal=24, vertical=12),
        border=ft.border.only(bottom=ft.BorderSide(1, t.border)),
    )


def main(page: ft.Page) -> None:
    """Точка входа Flet приложения."""
    page.title = "Finist Crawler"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1200
    page.window.height = 800
    page.window.min_width = 960
    page.window.min_height = 640
    page.padding = 0
    page.fonts = {
        "Inter": _resolve_font("assets/fonts/Inter-Regular.ttf"),
        "JetBrains Mono": _resolve_font("assets/fonts/JetBrainsMono-Regular.ttf"),
    }

    ctrl = AppController(page)
    page.bgcolor = ctrl.theme.tokens.bg_primary
    page.theme_mode = ft.ThemeMode.DARK if ctrl.theme.is_dark else ft.ThemeMode.LIGHT

    try:
        from ui.pages.launcher import LauncherPage

        launcher = LauncherPage(ctrl)
    except ImportError:
        launcher = _PlaceholderPage("🚀 Запуск")

    try:
        from ui.pages.monitor import MonitorPage

        monitor = MonitorPage(ctrl)
    except ImportError:
        monitor = _PlaceholderPage("📊 Мониторинг")

    try:
        from ui.pages.results import ResultsPage

        results = ResultsPage(ctrl)
    except ImportError:
        results = _PlaceholderPage("📁 Результаты")

    pages = {
        "launcher": launcher,
        "monitor": monitor,
        "results": results,
    }

    current_route: list[str] = ["launcher"]

    def navigate(route: str) -> None:
        current_route[0] = route
        _rebuild(route)

    def on_theme_toggle() -> None:
        ctrl.theme.toggle()
        page.theme_mode = ft.ThemeMode.DARK if ctrl.theme.is_dark else ft.ThemeMode.LIGHT
        page.bgcolor = ctrl.theme.tokens.bg_primary
        _rebuild(current_route[0])

    def _rebuild(route: str) -> None:
        page.controls.clear()
        nav_bar = _build_nav_bar(route, navigate, ctrl, on_theme_toggle)
        content = ft.Container(
            content=pages[route].build(),
            expand=True,
            bgcolor=ctrl.theme.tokens.bg_primary,
        )
        page.controls.append(
            ft.Column(
                controls=[nav_bar, content],
                spacing=0,
                expand=True,
            )
        )
        if route == "monitor" and hasattr(monitor, "start_monitoring"):
            monitor.start_monitoring()
        page.update()

    ctrl.navigate = navigate

    def on_window_event(e: ft.WindowEvent) -> None:
        if e.type == ft.WindowEventType.CLOSE:
            ctrl.cleanup()

    page.on_window_event = on_window_event

    navigate("launcher")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    setup_environment()
    ft.app(target=main)
