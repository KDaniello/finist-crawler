from __future__ import annotations

import datetime
import logging
import threading

import flet as ft

from core.telemetry import TelemetryEvent, TelemetryEventType

logger = logging.getLogger(__name__)

# Человекочитаемые названия источников
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

_SOURCE_ICONS = {
    "habr_articles": "📰",
    "lenta_articles": "📡",
    "reddit_discussions": "💬",
    "steam_reviews": "🎮",
    "otzovik_reviews": "⭐",
    "twogis_reviews": "🗺️",
}


def _records_label(source_key: str, count: int) -> str:
    """Возвращает читаемую подпись: 'собрано 42 отзыва'."""
    for key, label in _SOURCE_LABELS.items():
        if key in source_key.lower():
            return f"{count} {label}"
    return f"{count} записей"


class MonitorPage:
    """Страница мониторинга активного парсинга."""

    MAX_LOG_LINES = 100

    def __init__(self, controller: object) -> None:
        self._ctrl = controller
        self._branch_bars: dict[str, ft.ProgressBar] = {}
        self._branch_texts: dict[str, ft.Text] = {}
        self._branch_rows: dict[str, ft.Column] = {}
        self._is_monitoring = False
        self._total_records = 0
        self._source_key: str = ""

        t = self._ctrl.theme.tokens

        self._status_text = ft.Text(
            "Ожидание запуска...",
            size=13,
            color=t.text_secondary,
            font_family="Inter",
        )
        self._records_text = ft.Text(
            "0",
            size=36,
            weight=ft.FontWeight.BOLD,
            color=t.accent,
            font_family="Inter",
        )
        self._records_label = ft.Text(
            "записей собрано",
            size=12,
            color=t.text_muted,
            font_family="Inter",
        )
        self._cpu_bar = ft.ProgressBar(
            value=0,
            color=t.accent_info,
            bgcolor=t.border,
            expand=True,
        )
        self._ram_bar = ft.ProgressBar(
            value=0,
            color=t.accent,
            bgcolor=t.border,
            expand=True,
        )
        self._cpu_text = ft.Text(
            "0%",
            size=12,
            color=t.text_secondary,
            font_family="Inter",
            width=40,
        )
        self._ram_text = ft.Text(
            "0%",
            size=12,
            color=t.text_secondary,
            font_family="Inter",
            width=40,
        )
        self._app_mem_text = ft.Text(
            "Приложение: 0 MB",
            size=12,
            color=t.text_muted,
            font_family="Inter",
        )
        self._branches_col = ft.Column([], spacing=10)
        self._completed_col = ft.Column([], spacing=4)
        self._log_col = ft.Column([], spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self._stop_btn = ft.Container(
            content=ft.Text(
                "Остановить",
                size=13,
                weight=ft.FontWeight.W_500,
                color="#FFFFFF",
                font_family="Inter",
            ),
            bgcolor=t.accent_danger,
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=20, vertical=10),
            on_click=self._on_stop,
            ink=True,
            visible=False,
        )

    def _reset_state(self) -> None:
        """Сбрасывает состояние UI перед новым парсингом."""
        self._total_records = 0
        self._source_key = ""
        self._branch_bars.clear()
        self._branch_texts.clear()
        self._branch_rows.clear()
        self._branches_col.controls.clear()
        self._completed_col.controls.clear()
        self._log_col.controls.clear()
        t = self._ctrl.theme.tokens
        self._records_text.value = "0"
        self._records_label.value = "записей собрано"
        self._status_text.value = "Инициализация..."
        self._status_text.color = t.text_secondary

    def build(self) -> ft.Control:
        t = self._ctrl.theme.tokens

        # Карточка статуса — компактная
        status_card = ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            self._records_text,
                            self._records_label,
                            ft.Container(height=4),
                            self._status_text,
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    self._stop_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=t.bg_secondary,
            border_radius=16,
            padding=20,
            border=ft.border.all(1, t.border),
            expand=True,
        )

        # Карточка ресурсов — компактная
        resources_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Ресурсы",
                        size=11,
                        color=t.text_muted,
                        font_family="Inter",
                        weight=ft.FontWeight.W_500,
                    ),
                    ft.Row(
                        [
                            ft.Text(
                                "CPU", size=11, color=t.text_muted, font_family="Inter", width=32
                            ),
                            ft.Container(content=self._cpu_bar, expand=True),
                            self._cpu_text,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            ft.Text(
                                "RAM", size=11, color=t.text_muted, font_family="Inter", width=32
                            ),
                            ft.Container(content=self._ram_bar, expand=True),
                            self._ram_text,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._app_mem_text,
                ],
                spacing=6,
            ),
            bgcolor=t.bg_secondary,
            border_radius=16,
            padding=20,
            border=ft.border.all(1, t.border),
            width=260,
        )

        # Активные + завершённые в одной строке
        progress_row = ft.Row(
            [
                # Активные ветки
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "В процессе",
                                size=11,
                                color=t.text_muted,
                                font_family="Inter",
                                weight=ft.FontWeight.W_500,
                            ),
                            self._branches_col,
                        ],
                        spacing=10,
                    ),
                    bgcolor=t.bg_secondary,
                    border_radius=16,
                    padding=20,
                    border=ft.border.all(1, t.border),
                    expand=True,
                ),
                # Завершённые
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Завершено",
                                size=11,
                                color=t.text_muted,
                                font_family="Inter",
                                weight=ft.FontWeight.W_500,
                            ),
                            self._completed_col,
                        ],
                        spacing=8,
                    ),
                    bgcolor=t.bg_secondary,
                    border_radius=16,
                    padding=20,
                    border=ft.border.all(1, t.border),
                    expand=True,
                ),
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Логи — фиксированная высота, не растут
        logs_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Журнал событий",
                        size=11,
                        color=t.text_muted,
                        font_family="Inter",
                        weight=ft.FontWeight.W_500,
                    ),
                    ft.Container(
                        content=self._log_col,
                        height=160,
                        bgcolor=t.bg_primary,
                        border_radius=10,
                        padding=10,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                ],
                spacing=8,
            ),
            bgcolor=t.bg_secondary,
            border_radius=16,
            padding=20,
            border=ft.border.all(1, t.border),
        )

        return ft.Container(
            content=ft.Column(
                [
                    # Заголовок
                    ft.Column(
                        [
                            ft.Text(
                                "Мониторинг",
                                size=22,
                                weight=ft.FontWeight.BOLD,
                                color=t.text_primary,
                                font_family="Inter",
                            ),
                            ft.Text(
                                "Отслеживание активного парсинга",
                                size=14,
                                color=t.text_secondary,
                                font_family="Inter",
                            ),
                        ],
                        spacing=4,
                    ),
                    ft.Row(
                        [status_card, resources_card],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    progress_row,
                    logs_card,
                ],
                spacing=14,
                # НЕТ scroll — всё на одном экране
            ),
            padding=ft.padding.symmetric(horizontal=32, vertical=20),
            expand=True,
            bgcolor=t.bg_primary,
        )

    def start_monitoring(self) -> None:
        """
        Вызывается при каждом переходе на страницу мониторинга.
        Сбрасывает старые данные если парсинг уже завершён.
        """
        t = self._ctrl.theme.tokens

        # Если новый парсинг — сбрасываем состояние
        if not self._is_monitoring:
            self._reset_state()

            # Определяем source_key из активных specs
            if self._ctrl.active_specs:
                spec = self._ctrl.active_specs[0].replace(".yaml", "")
                self._source_key = spec

            self._is_monitoring = True
            self._stop_btn.visible = True

            # Обновляем label записей на основе источника
            self._records_label.value = (
                _records_label(self._source_key, 0).replace("0 ", "") + " собрано"
            )

            # Подключаем хендлер логов ОДИН РАЗ
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
        import time

        while self._is_monitoring:
            try:
                stats = self._ctrl.monitor.get_stats()
                self._ctrl.page.run_task(self._update_resources_ui, stats)
            except Exception as e:
                logger.debug("Ошибка мониторинга: %s", e)
            time.sleep(2.0)

    async def _update_resources_ui(self, stats: object) -> None:
        t = self._ctrl.theme.tokens
        self._cpu_bar.value = stats.cpu_percent / 100
        self._cpu_text.value = f"{stats.cpu_percent:.0f}%"
        self._ram_bar.value = stats.ram_percent / 100
        self._ram_text.value = f"{stats.ram_percent:.0f}%"
        self._app_mem_text.value = f"Приложение: {stats.app_memory_mb:.0f} MB"

        if not self._ctrl.is_running() and self._is_monitoring:
            self._is_monitoring = False
            self._stop_btn.visible = False
            self._status_text.value = "Парсинг завершён"
            self._status_text.color = t.accent

        self._ctrl.page.update()

    def _create_log_handler(self) -> logging.Handler:
        monitor = self

        class _UILogHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = record.getMessage()
                    event = TelemetryEvent.from_log_message(msg)
                    if event is not None:
                        monitor._ctrl.page.run_task(monitor._apply_telemetry, event)
                        return
                    if record.levelno < logging.INFO:
                        return
                    monitor._ctrl.page.run_task(monitor._add_log_line, record)
                except Exception:
                    pass

        handler = _UILogHandler()
        handler.setLevel(logging.DEBUG)
        return handler

    async def _apply_telemetry(self, event: TelemetryEvent) -> None:
        t = self._ctrl.theme.tokens

        if event.event_type == TelemetryEventType.PAGE_START:
            self._status_text.value = f"Страница {event.page_number}..."
            self._status_text.color = t.text_secondary

        elif event.event_type == TelemetryEventType.PROGRESS:
            branch = event.branch_url or ""
            current = event.current or 0
            total = event.total or 0
            self._update_branch_bar(branch, current, total)

        elif event.event_type == TelemetryEventType.BRANCH_DONE:
            branch = event.branch_url or ""
            final = event.current or 0
            self._total_records += final

            # Обновляем счётчик с читаемой подписью
            self._records_text.value = str(self._total_records)
            self._records_label.value = (
                _records_label(self._source_key, self._total_records)
                .replace(str(self._total_records), "")
                .strip()
                + " собрано"
            )

            # Убираем активный прогресс-бар
            if branch in self._branch_rows:
                row = self._branch_rows[branch]
                if row in self._branches_col.controls:
                    self._branches_col.controls.remove(row)
                del self._branch_rows[branch]
            if branch in self._branch_bars:
                del self._branch_bars[branch]
            if branch in self._branch_texts:
                del self._branch_texts[branch]

            # Добавляем в завершённые
            name = self._branch_name(branch)
            done_line = ft.Row(
                [
                    ft.Container(
                        width=6,
                        height=6,
                        border_radius=3,
                        bgcolor=t.accent,
                    ),
                    ft.Text(
                        name,
                        size=12,
                        color=t.text_secondary,
                        font_family="Inter",
                        expand=True,
                    ),
                    ft.Text(
                        _records_label(self._source_key, final),
                        size=12,
                        color=t.accent,
                        font_family="Inter",
                    ),
                ],
                spacing=8,
            )
            self._completed_col.controls.insert(0, done_line)
            if len(self._completed_col.controls) > 10:
                self._completed_col.controls.pop()

        elif event.event_type == TelemetryEventType.CAPTCHA_WAITING:
            secs = event.seconds_remaining or 0
            self._status_text.value = f"Капча — решите в браузере ({secs} сек.)"
            self._status_text.color = t.accent_danger

        elif event.event_type == TelemetryEventType.CAPTCHA_SOLVED:
            self._status_text.value = "Капча пройдена, продолжаем..."
            self._status_text.color = t.accent

        self._ctrl.page.update()

    def _branch_name(self, branch: str) -> str:
        """Извлекает читаемое имя из URL ветки."""
        url_parts = [p for p in branch.strip("/").split("/") if p]
        skip = {"reviews", "comments", "json", ""}
        clean_parts = [p for p in url_parts if p not in skip and not p.endswith(".json")]
        if len(clean_parts) >= 2:
            name = clean_parts[-2]
        elif clean_parts:
            name = clean_parts[-1]
        else:
            name = branch[:30]
        return name[:40] + "..." if len(name) > 40 else name

    def _update_branch_bar(self, branch: str, current: int, total: int) -> None:
        t = self._ctrl.theme.tokens
        name = self._branch_name(branch)
        effective_total = total if total > 0 else current + 50
        value = min(current / effective_total, 1.0) if effective_total > 0 else 0
        total_str = str(total) if total > 0 else "?"
        count_str = _records_label(self._source_key, current)

        if branch not in self._branch_bars:
            bar = ft.ProgressBar(
                value=value,
                color=t.accent,
                bgcolor=t.border,
                expand=True,
                border_radius=4,
            )
            label = ft.Text(
                name,
                size=12,
                color=t.text_secondary,
                font_family="Inter",
                expand=True,
            )
            count = ft.Text(
                f"{count_str} / {total_str}",
                size=11,
                color=t.text_muted,
                font_family="Inter",
            )
            row = ft.Column(
                [
                    ft.Row(
                        [label, count],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bar,
                ],
                spacing=4,
            )
            self._branch_bars[branch] = bar
            self._branch_texts[branch] = count
            self._branch_rows[branch] = row
            self._branches_col.controls.append(row)
        else:
            self._branch_bars[branch].value = value
            self._branch_texts[branch].value = f"{count_str} / {total_str}"

    async def _add_log_line(self, record: logging.LogRecord) -> None:
        t = self._ctrl.theme.tokens
        level_colors = {
            logging.INFO: t.text_secondary,
            logging.WARNING: t.accent_warn,
            logging.ERROR: t.accent_danger,
            logging.CRITICAL: t.accent_danger,
        }
        color = level_colors.get(record.levelno, t.text_muted)
        time_str = datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        line = ft.Text(
            f"{time_str}  {record.getMessage()[:120]}",
            size=11,
            color=color,
            font_family="JetBrains Mono",
            selectable=True,
        )
        self._log_col.controls.append(line)

        # Лимит строк — удаляем старые сверху
        if len(self._log_col.controls) > self.MAX_LOG_LINES:
            self._log_col.controls.pop(0)

        self._ctrl.page.update()

    def _on_stop(self, e: ft.ControlEvent) -> None:
        t = self._ctrl.theme.tokens
        self._ctrl.stop_parsing()
        self._is_monitoring = False
        self._stop_btn.visible = False
        self._status_text.value = "Остановлено"
        self._status_text.color = t.accent_warn
        self._ctrl.page.update()
