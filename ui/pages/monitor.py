from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

import flet as ft

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

        # Состояние мониторинга
        self._is_monitoring = False
        self._total_records = 0
        self._source_key: str = ""
        self._start_time: float | None = None

        # Накапливаем записи по веткам для корректного подсчёта
        self._branch_records: dict[str, int] = defaultdict(int)

        # Ожидаемое число записей (из plan.max_records)
        self._expected_total: int | None = None

        # Защита от двойного показа completion
        self._completion_shown = False

        # Лог-хендлер для перехвата телеметрии
        self._log_handler: logging.Handler | None = None

        t = self._ctrl.theme.tokens

        # --- UI-компоненты ---
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
            value=None,  # None = indeterminate (анимация)
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
        self._page_info_text = ft.Text(
            "",
            size=SIZE_CAPTION,
            color=t.text_tertiary,
            font_family=FONT_TEXT,
        )
        self._completion_col = ft.Column(
            [],
            spacing=SPACE_MD,
            visible=False,
        )

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

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _reset_state(self) -> None:
        """Сброс всего состояния перед новым запуском."""
        self._total_records = 0
        self._source_key = ""
        self._start_time = None
        self._branch_records.clear()
        self._expected_total = None
        self._completion_shown = False

        self._completion_col.controls.clear()
        self._completion_col.visible = False

        t = self._ctrl.theme.tokens
        self._overall_bar.value = None  # indeterminate
        self._overall_count.value = "0 записей"
        self._status_text.value = "Инициализация..."
        self._status_text.color = t.text_secondary
        self._speed_text.value = "Скорость: — зап/с"
        self._elapsed_text.value = "Прошло: 00:00:00"
        self._page_info_text.value = ""

    @property
    def _target_records(self) -> int | None:
        """Целевое кол-во записей из настроек запуска."""
        return self._ctrl.active_max_records

    def _calc_progress(self) -> float | None:
        """
        Возвращает float [0..1] для прогресс-бара или None (indeterminate).
        Приоритет: max_records из настроек → expected_total из телеметрии.
        """
        target = self._target_records or self._expected_total
        if target and target > 0 and self._total_records >= 0:
            return min(self._total_records / target, 1.0)
        return None

    def _progress_label(self) -> str:
        current = self._total_records
        target = self._target_records or self._expected_total
        label = _records_label(self._source_key, current)
        if target and target > 0:
            return f"{label} из ~{target}"
        return label

    def _format_elapsed(self, elapsed: float) -> str:
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"Прошло: {hours:02d}:{minutes:02d}:{seconds:02d}"

    def _format_elapsed_short(self, elapsed: float) -> str:
        if elapsed < 60:
            return f" за {elapsed:.0f} сек."
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        return f" за {mins} мин. {secs} сек."

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> ft.Control:
        t = self._ctrl.theme.tokens

        back_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Text("←", size=SIZE_BODY, color=t.accent, font_family=FONT_TEXT),
                    ft.Text("Назад", size=SIZE_BODY, color=t.accent, font_family=FONT_TEXT),
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
                    self._page_info_text,
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

    # ------------------------------------------------------------------
    # Запуск мониторинга
    # ------------------------------------------------------------------

    def start_monitoring(self) -> None:
        """
        Вызывается из AppController сразу после старта процесса парсинга.
        Регистрирует лог-хендлер и запускает таймер.
        """
        if self._is_monitoring:
            return

        self._reset_state()

        # Определяем источник из активных спек
        if self._ctrl.active_specs:
            spec = self._ctrl.active_specs[0]
            self._source_key = spec.replace(".yaml", "")
            self._subtitle_text.value = _source_display_name(spec)

        # Ожидаемое кол-во из настроек
        self._expected_total = self._ctrl.active_max_records

        self._start_time = time.time()
        self._is_monitoring = True
        self._stop_btn.visible = True

        # Регистрируем лог-хендлер ПЕРЕД стартом потока таймера
        self._ensure_log_handler()

        # Поток обновления таймера и watchdog
        threading.Thread(
            target=self._ticker_loop,
            daemon=True,
            name="MonitorTicker",
        ).start()

    def _ensure_log_handler(self) -> None:
        if self._log_handler is not None:
            return

        monitor = self

        class _TelemetryHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = record.getMessage()
                    if not msg.startswith("TELEMETRY|"):
                        return
                    event = TelemetryEvent.from_log_message(msg)
                    if event is not None:
                        monitor._ctrl.page.run_task(monitor._apply_telemetry, event)
                except Exception:
                    pass

        handler = _TelemetryHandler()
        handler.setLevel(logging.DEBUG)
        self._log_handler = handler

        added = self._ctrl.log_manager.add_handler(handler)
        if not added:
            # Этого не должно происходить после исправления app.py,
            # но на случай edge-case логируем
            logger.error("Не удалось добавить TelemetryHandler — listener не инициализирован!")
        else:
            logger.debug("TelemetryHandler успешно добавлен в QueueListener")

        self._ctrl._ui_log_handler = handler

        class _TelemetryHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = record.getMessage()
                    if not msg.startswith("TELEMETRY|"):
                        return
                    event = TelemetryEvent.from_log_message(msg)
                    if event is not None:
                        # run_task — потокобезопасный вызов корутины в event loop flet
                        monitor._ctrl.page.run_task(monitor._apply_telemetry, event)
                except Exception:
                    pass

        handler = _TelemetryHandler()
        handler.setLevel(logging.DEBUG)
        self._log_handler = handler

        # Вешаем на корневой логгер — перехватываем ВСЕ сообщения
        # (включая из дочерних процессов через QueueHandler)
        added = False
        if hasattr(self._ctrl, "log_manager") and self._ctrl.log_manager is not None:
            added = self._ctrl.log_manager.add_handler(handler)

        if not added:
            # Фоллбэк: вешаем напрямую на root logger
            root = logging.getLogger()
            root.addHandler(handler)
            logger.debug("TelemetryHandler добавлен напрямую на root logger")

        # Сохраняем ссылку в контроллере для совместимости
        if hasattr(self._ctrl, "_ui_log_handler"):
            self._ctrl._ui_log_handler = handler

    def _remove_log_handler(self) -> None:
        if self._log_handler is None:
            return
        try:
            self._ctrl.log_manager.remove_handler(self._log_handler)
        except Exception:
            pass
        self._log_handler = None
        self._ctrl._ui_log_handler = None

    # ------------------------------------------------------------------
    # Ticker (фоновый поток)
    # ------------------------------------------------------------------

    def _ticker_loop(self) -> None:
        """
        Обновляет таймер каждую секунду.
        Также выступает watchdog: если процесс завершился, а WORKER_DONE
        не пришёл — показываем результат по факту.
        """
        while self._is_monitoring:
            try:
                self._ctrl.page.run_task(self._tick_ui)
            except Exception as e:
                logger.debug("Ticker error: %s", e)
            time.sleep(1.0)

    async def _tick_ui(self) -> None:
        """Обновление таймера и watchdog-проверка завершения."""
        if self._start_time is None:
            return

        t = self._ctrl.theme.tokens
        elapsed = time.time() - self._start_time

        # Обновляем таймер
        self._elapsed_text.value = self._format_elapsed(elapsed)

        # Скорость
        if elapsed > 0 and self._total_records > 0:
            speed = self._total_records / elapsed
            self._speed_text.value = f"Скорость: {speed:.1f} зап/с"

        # Watchdog: процесс завершился, но WORKER_DONE не пришёл
        if not self._ctrl.is_running() and self._is_monitoring and not self._completion_shown:
            logger.debug("Watchdog: процесс завершён без WORKER_DONE, показываем результат")
            self._is_monitoring = False
            self._stop_btn.visible = False
            self._overall_bar.value = 1.0

            elapsed_str = self._format_elapsed_short(elapsed)
            records = self._total_records

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

        self._ctrl.page.update()

    # ------------------------------------------------------------------
    # Применение телеметрии
    # ------------------------------------------------------------------

    async def _apply_telemetry(self, event: TelemetryEvent) -> None:
        """
        Главный обработчик телеметрических событий.
        Вызывается в event loop flet → безопасно обновлять UI.
        """
        t = self._ctrl.theme.tokens

        if event.event_type == TelemetryEventType.WORKER_STARTED:
            self._status_text.value = "Инициализация парсера..."
            self._status_text.color = t.text_secondary

        elif event.event_type == TelemetryEventType.PAGE_START:
            page_num = event.page_number or "?"
            self._page_info_text.value = f"Страница {page_num}"
            self._status_text.value = f"Загрузка страницы {page_num}..."
            self._status_text.color = t.text_secondary
            # Пока не знаем прогресс — indeterminate
            if self._overall_bar.value is None:
                pass  # уже indeterminate

        elif event.event_type == TelemetryEventType.PROGRESS:
            current = event.current or 0
            self._total_records = current

            # Обновляем ожидаемый total из телеметрии если не задан вручную
            if event.total and event.total > 0 and self._expected_total is None:
                self._expected_total = event.total

            self._overall_count.value = self._progress_label()

            # Прогресс-бар
            bar_val = self._calc_progress()
            self._overall_bar.value = bar_val  # None = indeterminate, float = determinate

            self._status_text.value = "Сбор данных..."
            self._status_text.color = t.accent

        elif event.event_type == TelemetryEventType.BRANCH_DONE:
            branch = event.branch_url or ""
            branch_count = event.current or 0
            # Фиксируем финальное кол-во для ветки
            self._branch_records[branch] = branch_count
            # total_records = сумма всех завершённых веток
            # (не перезаписываем полностью — может быть несколько веток)

        elif event.event_type == TelemetryEventType.CAPTCHA_WAITING:
            secs = event.seconds_remaining or 0
            self._status_text.value = f"🛡 Капча — решите в браузере ({secs} сек.)"
            self._status_text.color = t.accent_danger

        elif event.event_type == TelemetryEventType.CAPTCHA_SOLVED:
            self._status_text.value = "✅ Капча пройдена, продолжаем..."
            self._status_text.color = t.accent

        elif event.event_type == TelemetryEventType.WORKER_DONE:
            if self._completion_shown:
                # Защита от дублирования
                self._ctrl.page.update()
                return

            records = event.current if event.current is not None else self._total_records
            self._total_records = records
            self._is_monitoring = False
            self._stop_btn.visible = False
            self._completion_shown = True
            self._remove_log_handler()

            elapsed_str = ""
            if self._start_time is not None:
                elapsed_str = self._format_elapsed_short(time.time() - self._start_time)

            if records == 0:
                self._status_text.value = "По запросу ничего не найдено"
                self._status_text.color = t.accent_warn
                self._overall_bar.value = 0.0
                self._show_completion(
                    "ℹ️",
                    "По запросу ничего не найдено. Попробуйте другое ключевое слово.",
                    t.accent_warn,
                    "← Вернуться к поиску",
                    "launcher",
                )
            else:
                self._status_text.value = "Сбор завершён"
                self._status_text.color = t.success
                self._overall_bar.value = 1.0
                self._overall_count.value = self._progress_label()
                self._show_completion(
                    "✅",
                    f"Сбор завершён. {_records_label(self._source_key, records)}{elapsed_str}",
                    t.success,
                    "Посмотреть результаты →",
                    "results",
                )

        elif event.event_type == TelemetryEventType.WORKER_ERROR:
            if self._completion_shown:
                self._ctrl.page.update()
                return

            msg = event.error_message or "Неизвестная ошибка"
            self._status_text.value = f"Ошибка: {msg[:80]}"
            self._status_text.color = t.accent_danger
            self._stop_btn.visible = False
            self._is_monitoring = False
            self._completion_shown = True
            self._overall_bar.value = 0.0
            self._remove_log_handler()

            self._show_completion(
                "⚠️",
                f"Произошла ошибка: {msg[:100]}",
                t.accent_danger,
                "← Вернуться к поиску",
                "launcher",
            )

        self._ctrl.page.update()

    # ------------------------------------------------------------------
    # Completion card
    # ------------------------------------------------------------------

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
                            padding=ft.Padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
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

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

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
                    style=ft.ButtonStyle(color=t.accent_warn),
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
        self._status_text.value = "Остановлено пользователем"
        self._status_text.color = t.accent_warn
        self._overall_bar.value = self._calc_progress() or 0.0
        self._remove_log_handler()
        self._completion_shown = True

        # Показываем карточку с тем, что успели собрать
        records = self._total_records
        if records > 0:
            self._show_completion(
                "⏹",
                f"Сбор остановлен. Сохранено: {_records_label(self._source_key, records)}.",
                t.accent_warn,
                "Посмотреть результаты →",
                "results",
            )
        else:
            self._show_completion(
                "⏹",
                "Сбор остановлен до получения данных.",
                t.accent_warn,
                "← Вернуться к поиску",
                "launcher",
            )

        self._ctrl.page.update()
