from __future__ import annotations

import logging
import math
import re
from typing import Any

import flet as ft

from core import JobConfig
from ui.app import AppController
from ui.theme import (
    FONT_DISPLAY,
    FONT_TEXT,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    RADIUS_XL,
    SIZE_BODY,
    SIZE_CAPTION,
    SIZE_HEADING,
    SIZE_LABEL,
    SIZE_TITLE,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
)

logger = logging.getLogger(__name__)

_RECORDS_PER_PAGE: dict[str, int] = {
    "reddit": 25,
    "reddit_discussions": 25,
    "twogis": 30,
    "twogis_reviews": 30,
    "steam": 20,
    "steam_reviews": 20,
    "habr": 20,
    "habr_articles": 20,
    "lenta": 20,
    "lenta_articles": 20,
    "otzovik": 10,
    "otzovik_reviews": 10,
}

_PRESETS: list[tuple[str, int]] = [
    ("Немного (~100)", 100),
    ("Стандарт (~500)", 500),
    ("Много (~2000)", 2000),
    ("Всё", 0),
]

_MAX_PAGES_CEILING = 50


class LauncherPage:
    """Страница запуска парсинга."""

    def __init__(self, controller: AppController, sources: list[dict[str, Any]]) -> None:
        self._ctrl = controller
        self._sources = sources
        self._selected_source: dict[str, Any] | None = None
        self._cards: list[ft.Container] = []
        self._preset_index: int = 1
        self._advanced_visible: bool = False

        t = self._ctrl.theme.tokens

        self._param_field = ft.TextField(
            hint_text="Сначала выберите источник",
            disabled=True,
            border_radius=RADIUS_MD,
            border_color=t.border,
            focused_border_color=t.border_focus,
            hint_style=ft.TextStyle(color=t.text_tertiary, font_family=FONT_TEXT),
            text_style=ft.TextStyle(color=t.text_primary, font_family=FONT_TEXT),
            bgcolor=t.bg_input,
            expand=True,
            cursor_color=t.accent,
            text_size=SIZE_BODY,
            on_change=self._on_param_change,  # type: ignore[arg-type]
        )
        self._records_field = ft.TextField(
            label="Сколько записей нужно",
            hint_text="Примерное количество",
            value="500",
            width=200,
            border_radius=RADIUS_MD,
            border_color=t.border,
            focused_border_color=t.border_focus,
            label_style=ft.TextStyle(
                color=t.text_secondary, font_family=FONT_TEXT, size=SIZE_LABEL
            ),
            hint_style=ft.TextStyle(
                color=t.text_tertiary, font_family=FONT_TEXT, size=SIZE_LABEL
            ),
            text_style=ft.TextStyle(
                color=t.text_primary, font_family=FONT_TEXT, size=SIZE_BODY
            ),
            bgcolor=t.bg_input,
            cursor_color=t.accent,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_records_change,  # type: ignore[arg-type]
        )
        self._depth_field = ft.TextField(
            label="Глубина поиска",
            hint_text="Страниц (1 стр ≈ 20-30 записей)",
            value="25",
            width=200,
            border_radius=RADIUS_MD,
            border_color=t.border,
            focused_border_color=t.border_focus,
            label_style=ft.TextStyle(
                color=t.text_secondary, font_family=FONT_TEXT, size=SIZE_LABEL
            ),
            hint_style=ft.TextStyle(
                color=t.text_tertiary, font_family=FONT_TEXT, size=SIZE_LABEL
            ),
            text_style=ft.TextStyle(
                color=t.text_primary, font_family=FONT_TEXT, size=SIZE_BODY
            ),
            bgcolor=t.bg_input,
            cursor_color=t.accent,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_depth_change,  # type: ignore[arg-type]
        )
        self._advanced_toggle = ft.Container(
            content=ft.Text(
                "Дополнительные настройки",
                size=SIZE_LABEL,
                color=t.accent,
                font_family=FONT_TEXT,
            ),
            on_click=self._toggle_advanced,  # type: ignore[arg-type]
            ink=True,
            padding=ft.Padding.symmetric(vertical=SPACE_XS),
        )
        self._advanced_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [self._records_field, self._depth_field],
                        spacing=SPACE_MD,
                    ),
                    ft.Text(
                        "Если на сайте меньше данных — соберём всё, что есть.",
                        size=SIZE_CAPTION,
                        color=t.text_tertiary,
                        font_family=FONT_TEXT,
                    ),
                ],
                spacing=SPACE_SM,
            ),
            visible=False,
        )
        self._start_btn = ft.Container(
            content=ft.Text(
                "Начать сбор данных",
                size=SIZE_BODY,
                weight=ft.FontWeight.W_600,
                color="#FFFFFF",
                font_family=FONT_TEXT,
                text_align=ft.TextAlign.CENTER,
            ),
            bgcolor=t.neutral,
            border_radius=RADIUS_MD,
            height=52,
            alignment=ft.Alignment(0, 0),
            on_click=self._on_start,  # type: ignore[arg-type]
            ink=True,
            opacity=0.4,
            disabled=True,
            tooltip="Выберите источник и введите запрос",
        )
        self._status_text = ft.Text(
            "",
            size=SIZE_LABEL,
            font_family=FONT_TEXT,
            color=t.text_secondary,
        )
        self._preset_buttons: list[ft.Container] = []
        self._preset_row: ft.Row = ft.Row([], spacing=SPACE_XS)

    def _get_records_per_page(self) -> int:
        if self._selected_source is None:
            return 20
        spec = self._selected_source.get("spec_name", "").replace(".yaml", "").lower()
        for key, val in _RECORDS_PER_PAGE.items():
            if key in spec:
                return val
        return 20

    def _calc_depth(self, records: int) -> int:
        rpp = self._get_records_per_page()
        if rpp <= 0:
            return _MAX_PAGES_CEILING
        return min(math.ceil(records / rpp), _MAX_PAGES_CEILING)

    def build(self) -> ft.Control:
        t = self._ctrl.theme.tokens
        self._cards.clear()

        for source in self._sources:
            card = self._build_source_card(source)
            self._cards.append(card)

        rows: list[ft.Control] = []
        per_row = 3
        for i in range(0, len(self._cards), per_row):
            rows.append(
                ft.Row(
                    controls=list[ft.Control](self._cards[i : i + per_row]),
                    spacing=SPACE_MD,
                )
            )
        source_grid = ft.Column(rows, spacing=SPACE_MD)

        self._build_presets()

        params_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Параметры запуска",
                        size=SIZE_HEADING,
                        weight=ft.FontWeight.W_600,
                        color=t.text_primary,
                        font_family=FONT_DISPLAY,
                    ),
                    ft.Container(height=SPACE_XS),
                    self._param_field,
                    ft.Container(height=SPACE_SM),
                    self._preset_row,
                    self._advanced_toggle,
                    self._advanced_panel,
                ],
                spacing=SPACE_SM,
            ),
            bgcolor=t.bg_elevated,
            border_radius=RADIUS_LG,
            padding=SPACE_LG,
            border=ft.Border.all(1, t.border_light),
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Выберите источник данных",
                        size=SIZE_TITLE,
                        weight=ft.FontWeight.BOLD,
                        color=t.text_primary,
                        font_family=FONT_DISPLAY,
                    ),
                    ft.Container(height=SPACE_XS),
                    source_grid,
                    ft.Container(height=SPACE_SM),
                    params_panel,
                    ft.Container(height=SPACE_SM),
                    self._start_btn,
                    self._status_text,
                ],
                spacing=SPACE_MD,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding.symmetric(horizontal=SPACE_XL, vertical=SPACE_LG),
            expand=True,
            bgcolor=t.bg_primary,
        )

    def _build_source_card(self, source: dict[str, Any]) -> ft.Container:
        t = self._ctrl.theme.tokens

        content_controls: list[ft.Control] = [
            ft.Text(source["icon"], size=SIZE_TITLE),
            ft.Container(height=SPACE_SM),
            ft.Text(
                source["title"],
                size=SIZE_BODY,
                weight=ft.FontWeight.W_600,
                color=t.text_primary,
                font_family=FONT_TEXT,
            ),
            ft.Text(
                source["description"],
                size=SIZE_LABEL,
                color=t.text_secondary,
                font_family=FONT_TEXT,
            ),
        ]
        speed_hint = source.get("speed_hint")
        if speed_hint:
            content_controls.append(
                ft.Text(
                    speed_hint,
                    size=SIZE_CAPTION,
                    color=t.text_tertiary,
                    font_family=FONT_TEXT,
                )
            )

        return ft.Container(
            content=ft.Column(content_controls, spacing=SPACE_XS),
            data=source,
            expand=True,
            height=140,
            border_radius=RADIUS_XL,
            bgcolor=t.bg_elevated,
            border=ft.Border.all(1, t.border_light),
            padding=SPACE_MD,
            on_click=self._on_card_click,  # type: ignore[arg-type]
            ink=True,
            animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        )

    def _build_presets(self) -> None:
        t = self._ctrl.theme.tokens
        self._preset_buttons.clear()
        for i, (label, _val) in enumerate(_PRESETS):
            is_selected = i == self._preset_index
            btn = ft.Container(
                content=ft.Text(
                    label,
                    size=SIZE_LABEL,
                    color=t.text_primary if is_selected else t.text_secondary,
                    font_family=FONT_TEXT,
                    weight=ft.FontWeight.W_600 if is_selected else ft.FontWeight.W_400,
                ),
                bgcolor=t.accent_light if is_selected else t.bg_overlay,
                border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                on_click=lambda e, idx=i: self._on_preset_click(idx),
                ink=True,
            )
            self._preset_buttons.append(btn)
        self._preset_row.controls = list[ft.Control](self._preset_buttons)

    def _on_preset_click(self, index: int) -> None:
        self._preset_index = index
        _, records = _PRESETS[index]
        if records > 0:
            self._records_field.value = str(records)
            self._depth_field.value = str(self._calc_depth(records))
        else:
            self._records_field.value = "0"
            self._depth_field.value = str(_MAX_PAGES_CEILING)
        self._build_presets()
        self._ctrl.page.update()

    def _toggle_advanced(self, e: ft.ControlEvent) -> None:
        t = self._ctrl.theme.tokens
        self._advanced_visible = not self._advanced_visible
        self._advanced_panel.visible = self._advanced_visible
        label = (
            "Скрыть настройки"
            if self._advanced_visible
            else "Дополнительные настройки"
        )
        self._advanced_toggle.content = ft.Text(
            label, size=SIZE_LABEL, color=t.accent, font_family=FONT_TEXT
        )
        self._ctrl.page.update()

    def _on_records_change(self, e: ft.ControlEvent) -> None:
        try:
            records = int(self._records_field.value or "0")
        except ValueError:
            return
        if records > 0:
            self._depth_field.value = str(self._calc_depth(records))
        self._ctrl.page.update()

    def _on_depth_change(self, e: ft.ControlEvent) -> None:
        try:
            depth = int(self._depth_field.value or "0")
        except ValueError:
            return
        rpp = self._get_records_per_page()
        if rpp > 0 and depth > 0:
            self._records_field.value = str(depth * rpp)
        self._ctrl.page.update()

    def _on_param_change(self, e: ft.ControlEvent) -> None:
        t = self._ctrl.theme.tokens
        param_value = (self._param_field.value or "").strip()
        if self._selected_source and param_value:
            self._start_btn.bgcolor = t.accent
            self._start_btn.opacity = 1.0
            self._start_btn.disabled = False
            self._start_btn.tooltip = ""
        else:
            self._start_btn.bgcolor = t.neutral
            self._start_btn.opacity = 0.4
            self._start_btn.disabled = True
            self._start_btn.tooltip = "Выберите источник и введите запрос"
        self._ctrl.page.update()

    def _on_card_click(self, e: ft.ControlEvent) -> None:
        t = self._ctrl.theme.tokens
        source = e.control.data

        for card in self._cards:
            card.border = ft.Border.all(1, t.border_light)
            card.bgcolor = t.bg_elevated

        e.control.border = ft.Border.all(2, t.accent)  # type: ignore[attr-defined]
        e.control.bgcolor = t.accent_light  # type: ignore[attr-defined]

        self._selected_source = source
        self._param_field.hint_text = source["param_hint"]
        self._param_field.disabled = False
        self._param_field.value = ""

        _, records = _PRESETS[self._preset_index]
        if records > 0:
            self._depth_field.value = str(self._calc_depth(records))
        else:
            self._depth_field.value = str(_MAX_PAGES_CEILING)

        self._start_btn.bgcolor = t.neutral
        self._start_btn.opacity = 0.4
        self._start_btn.disabled = True
        self._start_btn.tooltip = "Выберите источник и введите запрос"

        self._status_text.value = f"Выбран: {source['title']}"
        self._status_text.color = t.accent

        self._ctrl.page.update()

    def _on_start(self, e: ft.ControlEvent) -> None:
        t = self._ctrl.theme.tokens

        if self._ctrl.is_running():
            self._status_text.value = "Парсинг уже запущен"
            self._status_text.color = t.accent_warn
            self._ctrl.page.update()
            return

        source = self._selected_source
        if source is None:
            return

        param_value = (self._param_field.value or "").strip()
        if not param_value:
            self._status_text.value = "Введите параметр поиска"
            self._status_text.color = t.accent_danger
            self._ctrl.page.update()
            return

        if source["param_key"] == "app_id" and not param_value.isdigit():
            url_match = re.search(r"/app/(\d+)", param_value)
            if url_match:
                param_value = url_match.group(1)
                self._param_field.value = param_value
            else:
                self._status_text.value = "Введите числовой App ID или ссылку на игру"
                self._status_text.color = t.accent_danger
                self._ctrl.page.update()
                return

        if source["param_key"] == "direct_url" and not param_value.startswith("http"):
            self._status_text.value = "Введите корректный URL (https://...)"
            self._status_text.color = t.accent_danger
            self._ctrl.page.update()
            return

        try:
            max_pages = int(self._depth_field.value or "5")
        except ValueError:
            max_pages = 5

        try:
            max_records_val = int(self._records_field.value or "0")
        except ValueError:
            max_records_val = 0

        max_records = max_records_val if max_records_val > 0 else None

        if source["param_key"] == "direct_url":
            job = JobConfig(
                spec_name=source["spec_name"],
                max_pages=max_pages,
                max_records=max_records,
                direct_urls=[param_value],
            )
        else:
            job = JobConfig(
                spec_name=source["spec_name"],
                max_pages=max_pages,
                max_records=max_records,
                template_params={source["param_key"]: param_value},
            )

        success = self._ctrl.start_parsing([job])

        if success:
            self._status_text.value = "Запущено — переходим на мониторинг..."
            self._status_text.color = t.accent
            self._start_btn.opacity = 0.4
            self._start_btn.disabled = True
            self._ctrl.page.update()
            self._ctrl.page.run_task(self._delayed_navigate)
        else:
            self._status_text.value = "Не удалось запустить"
            self._status_text.color = t.accent_danger
            self._ctrl.page.update()

    async def _delayed_navigate(self) -> None:
        import asyncio

        await asyncio.sleep(0.5)
        self._ctrl.navigate("monitor")
