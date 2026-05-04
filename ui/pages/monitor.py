from __future__ import annotations

import logging
import threading
import time

import flet as ft

from core.resources import SystemStats
from core.telemetry import TelemetryEvent, TelemetryEventType
from ui.app import AppController
from ui.theme import (
    FONT_DISPLAY,
    FONT_TEXT,
    RADIUS_LG,
    RADIUS_SM,
    SIZE_BODY,
    SIZE_CAPTION,
    SIZE_HEADING,
    SIZE_LABEL,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
)

logger = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "habr": "статей",
    "habr_articles": "статей",
    "lenta": "статей",
    "lenta_articles": "статей",
    "reddit": "комментариев",
    "reddit_discussions": "комментариев",
    "steam": "отзывов",
    "steam_reviews": "отзывов",
    "otzovik": "отзывов",
    "otzovik_reviews": "отзывов",
    "twogis": "отзывов",
    "twogis_reviews": "отзывов",
}


def _records_label(source_key: str, count: int) -> str:
    for key, label in _SOURCE_LABELS.items():
        if key in source_key.lower():
            return f"{count} {label}"
    return f"{count} записей"


def _source_display_name(spec_name: str) -> str:
    clean = spec_name.replace(".yaml", "")
    for key in _SOURCE_LABELS:
        if key in clean.lower():
            parts = key.split("_")
            return parts[0].capitalize()
    return clean


class MonitorPage:
    """Страница мониторинга активного парсинга."""

    def __init__(self, controller: AppController) -> None:
        self._ctrl = controller
        self._is_monitoring = False
        self._total_records = 0
        self._source_key: str = ""
        self._start_time: float | None = None

        t = self._ctrl.theme.tokens

        self._status_text = ft.Text(
            "Ожидание запуска...",
            size=SIZE_LABEL,
            color=t.text_secondary,
            font_family=FONT_TEXT,
        )
        self._subtitle_text = ft.Text(
            "",
            size=SIZE_BODY,
            color=t.text_secondary,
            font_family=FONT_TEXT,
        )
        self._overall_bar = ft.ProgressBar(
            value=0,
            color=t.accent,
            bgcolor=t.border,
            border_radius=RADIUS_SM,
            bar_height=8,
        )
        self._overall_count = ft.Text(
            "0 записей",
            size=SIZE_LABEL,
            color=t.text_secondary,
            font_family=FONT_TEXT,
        )
        self._speed_text = ft.Text(
            "Скорость: — зап/с",
            size=SIZE_CAPTION,
            color=t.text_tertiary,
            font_family=FONT_TEXT,
        )
        self._elapsed_text = ft.Text(
            "Прошло: 00:00:00",
            size=SIZE_CAPTION,
            color=t.text_tertiary,
            font_family=FONT_TEXT,
        )
        self._completion_col = ft.Column([], spacing=SPACE_MD, visible=False)

        self._stop_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Text("■", size=SIZE_LABEL, color="#FFFFFF"),
                    ft.Text(
                        "Стоп",
                        size=SIZE_LABEL,
                        color="#FFFFFF",
                        font_family=FONT_TEXT,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
                spacing=SPACE_XS,
            ),
            bgcolor=t.accent_danger,
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=self._on_stop_click,  # type: ignore[arg-type]
            ink=True,
            visible=False,
        )

    def _reset_state(self) -> None:
        self._total_records = 0
        self._source_key = ""
        self._start_time = None
        self._completion_col.controls.clear()
        self._completion_col.visible = False
        t = self._ctrl.theme.tokens
        self._overall_bar.value = 0
        self._overall_count.value = "0 записей"
        self._status_text.value = "Инициализация..."
        self._status_text.color = t.text_secondary
        self._speed_text.value = "Скорость: — зап/с"
        self._elapsed_text.value = "Прошло: 00:00:00"

    @property
    def _target_records(self) -> int | None:
        return self._ctrl.active_max_records

    def _progress_label(self) -> str:
        current = self._total_records
        target = self._target_records
        if target and target > 0:
            return f"{_records_label(self._source_key, current)} из ~{target}"
        return _records_label(self._source_key, current)

    def build(self) -> ft.Control:
        t = self._ctrl.theme.tokens

        back_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Text("←", size=SIZE_BODY, color=t.accent, font_family=FONT_TEXT),
                    ft.Text(
                        "Назад",
                        size=SIZE_BODY,
                        color=t.accent,
                        font_family=FONT_TEXT,
                    ),
                ],
                spacing=SPACE_XS,
            ),
            on_click=lambda e: self._ctrl.navigate("launcher"),
            ink=True,
            padding=ft.Padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
            border_radius=RADIUS_SM,
        )

        header = ft.Row(
            [
                back_btn,
                ft.Text(
                    "Сбор данных",
                    size=SIZE_HEADING,
                    weight=ft.FontWeight.W_600,
                    color=t.text_primary,
                    font_family=FONT_DISPLAY,
                    expand=True,
                    text_align=ft.TextAlign.CENTER,
                ),
                self._stop_btn,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        progress_card = ft.Container(
            content=ft.Column(
                [
                    self._subtitle_text,
                    ft.Container(height=SPACE_SM),
                    self._overall_bar,
                    ft.Container(height=SPACE_XS),
                    self._overall_count,
                    ft.Container(height=SPACE_XS),
                    self._status_text,
                ],
                spacing=SPACE_XS,
            ),
            bgcolor=t.bg_elevated,
            border_radius=RADIUS_LG,
            padding=SPACE_LG,
            border=ft.Border.all(1, t.border_light),
        )

        metrics_row = ft.Row(
            [
                self._speed_text,
                ft.Container(width=SPACE_LG),
                self._elapsed_text,
            ],
            spacing=0,
        )

        return ft.Container(
            content=ft.Column(
                [
                    header,
                    progress_card,
                    metrics_row,
                    self._completion_col,
                ],
                spacing=SPACE_MD,
            ),
            padding=ft.Padding.symmetric(horizontal=SPACE_XL, vertical=SPACE_LG),
            expand=True,
            bgcolor=t.bg_primary,
        )

    def start_monitoring(self) -> None:
        if not self._is_monitoring:
            self._reset_state()

            if self._ctrl.active_specs:
                spec = self._ctrl.active_specs[0].replace(".yaml", "")
                self._source_key = spec
                display = _source_display_name(self._ctrl.active_specs[0])
                self._subtitle_text.value = display

            self._start_time = time.time()
            self._is_monitoring = True
            self._stop_btn.visible = True

            if self._ctrl._ui_log_handler is None:
                handler = self._create_log_handler()
                added = self._ctrl.log_manager.add_handler(handler)
                if added:
                    self._ctrl._ui_log_handler = handler

            threading.Thread(
                target=self._resource_monitor_loop,
                daemon=True,
                name="UIResourceMonitor",
            ).start()

    def _resource_monitor_loop(self) -> None:
        while self._is_monitoring:
            try:
                stats = self._ctrl.monitor.get_stats()
                self._ctrl.page.run_task(self._update_resources_ui, stats)
            except Exception as e:
                logger.debug("Ошибка мониторинга: %s", e)
            time.sleep(1.0)

    async def _update_resources_ui(self, stats: SystemStats) -> None:
        t = self._ctrl.theme.tokens

        if self._start_time is not None:
            elapsed = time.time() - self._start_time
            hours, remainder = divmod(int(elapsed), 3600)
            minutes, seconds = divmod(remainder, 60)
            self._elapsed_text.value = f"Прошло: {hours:02d}:{minutes:02d}:{seconds:02d}"

            if elapsed > 0 and self._total_records > 0:
                speed = self._total_records / elapsed
                self._speed_text.value = f"Скорость: {speed:.0f} зап/с"

        if not self._ctrl.is_running() and self._is_monitoring:
            self._is_monitoring = False
            self._stop_btn.visible = False
            self._status_text.value = "Сбор завершён"
            self._status_text.color = t.success

            elapsed_str = ""
            if self._start_time is not None:
                elapsed = time.time() - self._start_time
                if elapsed < 60:
                    elapsed_str = f" за {elapsed:.0f} сек."
                else:
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    elapsed_str = f" за {mins} мин. {secs} сек."

            rec_label = _records_label(
                self._source_key, self._total_records
            )
            self._show_completion(
                "✅",
                f"Сбор завершён. {rec_label}{elapsed_str}",
                t.success,
                "Посмотреть результаты →",
                "results",
            )

        self._ctrl.page.update()

    def _show_completion(
        self,
        icon: str,
        message: str,
        color: str,
        button_label: str,
        button_route: str,
    ) -> None:
        t = self._ctrl.theme.tokens
        self._completion_col.controls.clear()
        self._completion_col.controls.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(icon, size=SIZE_HEADING),
                        ft.Text(
                            message,
                            size=SIZE_BODY,
                            color=t.text_primary,
                            font_family=FONT_TEXT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(
                            content=ft.Text(
                                button_label,
                                size=SIZE_BODY,
                                color=t.accent,
                                font_family=FONT_TEXT,
                            ),
                            on_click=lambda e: self._ctrl.navigate(button_route),
                            ink=True,
                            padding=ft.Padding.symmetric(
                                horizontal=SPACE_MD, vertical=SPACE_SM
                            ),
                            border=ft.Border.all(1, t.accent),
                            border_radius=RADIUS_SM,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=SPACE_SM,
                ),
                bgcolor=t.bg_elevated,
                border_radius=RADIUS_LG,
                padding=SPACE_LG,
                border=ft.Border.all(1, t.border_light),
                alignment=ft.Alignment(0, 0),
            )
        )
        self._completion_col.visible = True

    def _create_log_handler(self) -> logging.Handler:
        monitor = self

        class _UILogHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = record.getMessage()
                    event = TelemetryEvent.from_log_message(msg)
                    if event is not None:
                        monitor._ctrl.page.run_task(monitor._apply_telemetry, event)
                except Exception:
                    pass

        handler = _UILogHandler()
        handler.setLevel(logging.DEBUG)
        return handler

    async def _apply_telemetry(self, event: TelemetryEvent) -> None:
        t = self._ctrl.theme.tokens

        if event.event_type == TelemetryEventType.PAGE_START:
            self._status_text.value = f"Загрузка страницы {event.page_number}..."
            self._status_text.color = t.text_secondary

        elif event.event_type == TelemetryEventType.PROGRESS:
            current = event.current or 0
            self._total_records = current
            self._overall_count.value = self._progress_label()
            target = self._target_records
            if target and target > 0:
                self._overall_bar.value = min(current / target, 1.0)
            elif current > 0:
                self._overall_bar.value = min(current / (current + 50), 0.95)
            self._status_text.value = "Сбор данных..."
            self._status_text.color = t.accent

        elif event.event_type == TelemetryEventType.BRANCH_DONE:
            final = event.current or 0
            self._total_records += final
            self._overall_count.value = self._progress_label()
            target = self._target_records
            if target and target > 0:
                self._overall_bar.value = min(self._total_records / target, 1.0)

        elif event.event_type == TelemetryEventType.CAPTCHA_WAITING:
            secs = event.seconds_remaining or 0
            self._status_text.value = f"Капча — решите в браузере ({secs} сек.)"
            self._status_text.color = t.accent_danger

        elif event.event_type == TelemetryEventType.CAPTCHA_SOLVED:
            self._status_text.value = "Капча пройдена, продолжаем..."
            self._status_text.color = t.accent

        elif event.event_type == TelemetryEventType.WORKER_DONE:
            records = event.current or 0
            self._total_records = records
            self._is_monitoring = False
            self._stop_btn.visible = False

            if records == 0:
                self._status_text.value = "По запросу ничего не найдено"
                self._status_text.color = t.accent_warn
                self._show_completion(
                    "ℹ️",
                    "По запросу ничего не найдено. Попробуйте другое ключевое слово.",
                    t.accent_warn,
                    "← Вернуться к поиску",
                    "launcher",
                )
            else:
                elapsed_str = ""
                if self._start_time is not None:
                    elapsed = time.time() - self._start_time
                    if elapsed < 60:
                        elapsed_str = f" за {elapsed:.0f} сек."
                    else:
                        mins = int(elapsed // 60)
                        secs = int(elapsed % 60)
                        elapsed_str = f" за {mins} мин. {secs} сек."
                self._status_text.value = "Сбор завершён"
                self._status_text.color = t.success
                self._overall_count.value = self._progress_label()
                self._show_completion(
                    "✅",
                    f"Сбор завершён. {_records_label(self._source_key, records)}{elapsed_str}",
                    t.success,
                    "Посмотреть результаты →",
                    "results",
                )

        elif event.event_type == TelemetryEventType.WORKER_ERROR:
            msg = event.error_message or "Неизвестная ошибка"
            self._status_text.value = f"Ошибка: {msg[:80]}"
            self._status_text.color = t.accent_danger
            self._stop_btn.visible = False
            self._is_monitoring = False
            self._show_completion(
                "⚠️",
                f"Произошла ошибка: {msg[:100]}",
                t.accent_danger,
                "← Вернуться к поиску",
                "launcher",
            )

        self._ctrl.page.update()

    def _on_stop_click(self, e: ft.ControlEvent) -> None:
        t = self._ctrl.theme.tokens
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Остановить сбор?",
                color=t.text_primary,
                font_family=FONT_DISPLAY,
            ),
            content=ft.Text(
                "Уже собранные данные сохранятся.",
                color=t.text_secondary,
                font_family=FONT_TEXT,
            ),
            actions=[
                ft.TextButton(
                    "Продолжить",
                    on_click=lambda _: self._close_dialog(),
                ),
                ft.TextButton(
                    "Остановить",
                    on_click=lambda _: self._confirm_stop(),
                    style=ft.ButtonStyle(color=t.warning),
                ),
            ],
        )
        self._ctrl.page.dialog = dlg  # type: ignore[attr-defined]
        self._ctrl.page.dialog.open = True  # type: ignore[attr-defined]
        self._ctrl.page.update()

    def _close_dialog(self) -> None:
        self._ctrl.page.dialog.open = False  # type: ignore[attr-defined]
        self._ctrl.page.update()

    def _confirm_stop(self) -> None:
        self._close_dialog()
        self._do_stop()

    def _do_stop(self) -> None:
        t = self._ctrl.theme.tokens
        self._ctrl.stop_parsing()
        self._is_monitoring = False
        self._stop_btn.visible = False
        self._status_text.value = "Остановлено"
        self._status_text.color = t.accent_warn
        self._ctrl.page.update()

    def _on_stop(self, e: ft.ControlEvent) -> None:
        self._do_stop()
