from __future__ import annotations

import logging

import flet as ft

from core import JobConfig

logger = logging.getLogger(__name__)

SOURCES = [
    {
        "spec_name": "habr_search.yaml",
        "title": "Хабр",
        "icon": "📰",
        "description": "Статьи и публикации",
        "param_label": "Ключевое слово",
        "param_hint": "Python, AI, DevOps...",
        "param_key": "keyword",
        "default_pages": 3,
        "default_detail_pages": 0,
        "tag": "Технологии",
    },
    {
        "spec_name": "reddit_comments.yaml",
        "title": "Reddit",
        "icon": "💬",
        "description": "Обсуждения и комментарии",
        "param_label": "Ключевое слово",
        "param_hint": "chatgpt, python...",
        "param_key": "keyword",
        "default_pages": 2,
        "default_detail_pages": 0,
        "tag": "Соцсети",
    },
    {
        "spec_name": "steam_reviews.yaml",
        "title": "Steam",
        "icon": "🎮",
        "description": "Отзывы на игры",
        "param_label": "App ID игры",
        "param_hint": "1091500 (Cyberpunk 2077)",
        "param_key": "app_id",
        "default_pages": 1,
        "default_detail_pages": 10,
        "tag": "Отзывы",
    },
    {
        "spec_name": "twogis_search.yaml",
        "title": "2GIS",
        "icon": "🗺️",
        "description": "Отзывы на организации",
        "param_label": "Название организации",
        "param_hint": "Вкусно и точка",
        "param_key": "keyword",
        "default_pages": 1,
        "default_detail_pages": 0,
        "tag": "Отзывы",
    },
    {
        "spec_name": "otzovik_reviews.yaml",
        "title": "Отзовик",
        "icon": "⭐",
        "description": "Отзывы на товары и услуги",
        "param_label": "URL страницы отзывов",
        "param_hint": "https://otzovik.com/reviews/...",
        "param_key": "direct_url",
        "default_pages": 5,
        "default_detail_pages": 0,
        "tag": "Отзывы",
    },
    {
        "spec_name": "lenta_search.yaml",
        "title": "Лента.ру",
        "icon": "📡",
        "description": "Новостные статьи",
        "param_label": "Ключевое слово",
        "param_hint": "санкции, экономика...",
        "param_key": "keyword",
        "default_pages": 5,
        "default_detail_pages": 0,
        "tag": "Новости",
    },
]


class LauncherPage:
    """Страница запуска парсинга."""

    def __init__(self, controller: object) -> None:
        self._ctrl = controller
        self._selected_source: dict | None = None
        self._cards: list[ft.Container] = []

        t = self._ctrl.theme.tokens

        self._param_field = ft.TextField(
            label="Параметр",
            hint_text="Сначала выберите источник",
            disabled=True,
            border_radius=10,
            border_color=t.border,
            focused_border_color=t.border_focus,
            label_style=ft.TextStyle(color=t.text_secondary, font_family="Inter"),
            hint_style=ft.TextStyle(color=t.text_muted, font_family="Inter"),
            text_style=ft.TextStyle(color=t.text_primary, font_family="Inter"),
            bgcolor=t.bg_input,
            expand=True,
            cursor_color=t.accent,
        )
        self._pages_slider = ft.Slider(
            min=1,
            max=20,
            value=5,
            divisions=19,
            label="{value}",
            active_color=t.accent,
            inactive_color=t.border,
            thumb_color=t.accent,
        )
        self._detail_slider = ft.Slider(
            min=0,
            max=50,
            value=0,
            divisions=50,
            label="{value}",
            active_color=t.accent,
            inactive_color=t.border,
            thumb_color=t.accent,
        )
        self._start_btn = ft.Container(
            content=ft.Text(
                "Начать парсинг",
                size=14,
                weight=ft.FontWeight.W_600,
                color="#FFFFFF",
                font_family="Inter",
                text_align=ft.TextAlign.CENTER,
            ),
            bgcolor=t.accent,
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=32, vertical=14),
            on_click=self._on_start,
            ink=True,
            opacity=0.4,
            disabled=True,
        )
        self._status_text = ft.Text(
            "",
            size=13,
            font_family="Inter",
            color=t.text_secondary,
        )

    def build(self) -> ft.Control:
        t = self._ctrl.theme.tokens
        self._cards.clear()

        for source in SOURCES:
            card = self._build_source_card(source)
            self._cards.append(card)

        # Сетка 3×2
        row1 = ft.Row(
            controls=self._cards[:3],
            spacing=12,
        )
        row2 = ft.Row(
            controls=self._cards[3:],
            spacing=12,
        )
        source_grid = ft.Column([row1, row2], spacing=12)

        # Панель параметров
        params_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Параметры запуска",
                        size=15,
                        weight=ft.FontWeight.W_600,
                        color=t.text_primary,
                        font_family="Inter",
                    ),
                    ft.Container(height=4),
                    self._param_field,
                    ft.Container(height=8),
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        "Глубина поиска",
                                        size=13,
                                        weight=ft.FontWeight.W_500,
                                        color=t.text_secondary,
                                        font_family="Inter",
                                    ),
                                    ft.Text(
                                        "Количество страниц результатов",
                                        size=11,
                                        color=t.text_muted,
                                        font_family="Inter",
                                    ),
                                    self._pages_slider,
                                ],
                                expand=True,
                                spacing=2,
                            ),
                            ft.Container(
                                width=1,
                                height=60,
                                bgcolor=t.border,
                                margin=ft.margin.symmetric(horizontal=8),
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Объём сбора",
                                        size=13,
                                        weight=ft.FontWeight.W_500,
                                        color=t.text_secondary,
                                        font_family="Inter",
                                    ),
                                    ft.Text(
                                        "0 = собрать всё найденное",
                                        size=11,
                                        color=t.text_muted,
                                        font_family="Inter",
                                    ),
                                    self._detail_slider,
                                ],
                                expand=True,
                                spacing=2,
                            ),
                        ],
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.START,
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
                                "Источник данных",
                                size=22,
                                weight=ft.FontWeight.BOLD,
                                color=t.text_primary,
                                font_family="Inter",
                            ),
                            ft.Text(
                                "Выберите платформу для сбора данных",
                                size=14,
                                color=t.text_secondary,
                                font_family="Inter",
                            ),
                        ],
                        spacing=4,
                    ),
                    ft.Container(height=4),
                    source_grid,
                    ft.Container(height=4),
                    params_panel,
                    ft.Container(height=4),
                    ft.Row(
                        [self._start_btn, self._status_text],
                        alignment=ft.MainAxisAlignment.START,
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.padding.symmetric(horizontal=32, vertical=28),
            expand=True,
            bgcolor=t.bg_primary,
        )

    def _build_source_card(self, source: dict) -> ft.Container:
        t = self._ctrl.theme.tokens

        tag_colors = {
            "Технологии": t.accent_info,
            "Соцсети": t.accent_info,
            "Отзывы": t.accent_warn,
            "Новости": t.accent,
        }
        tag_color = tag_colors.get(source.get("tag", ""), t.text_muted)

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(source["icon"], size=28),
                            ft.Container(expand=True),
                            ft.Container(
                                content=ft.Text(
                                    source.get("tag", ""),
                                    size=10,
                                    weight=ft.FontWeight.W_500,
                                    color=tag_color,
                                    font_family="Inter",
                                ),
                                bgcolor=ft.Colors.with_opacity(0.1, tag_color),
                                border_radius=6,
                                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                            ),
                        ],
                    ),
                    ft.Container(height=8),
                    ft.Text(
                        source["title"],
                        size=15,
                        weight=ft.FontWeight.W_600,
                        color=t.text_primary,
                        font_family="Inter",
                    ),
                    ft.Text(
                        source["description"],
                        size=12,
                        color=t.text_secondary,
                        font_family="Inter",
                    ),
                ],
                spacing=2,
            ),
            data=source,
            expand=True,
            height=140,
            border_radius=14,
            bgcolor=t.bg_secondary,
            border=ft.border.all(1, t.border),
            padding=16,
            on_click=self._on_card_click,
            ink=True,
            animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        )

    def _on_card_click(self, e: ft.ControlEvent) -> None:
        t = self._ctrl.theme.tokens
        source = e.control.data

        for card in self._cards:
            card.border = ft.border.all(1, t.border)
            card.bgcolor = t.bg_secondary

        e.control.border = ft.border.all(2, t.accent)
        e.control.bgcolor = ft.Colors.with_opacity(0.06, t.accent)

        self._selected_source = source
        self._param_field.label = source["param_label"]
        self._param_field.hint_text = source["param_hint"]
        self._param_field.disabled = False
        self._param_field.value = ""

        self._pages_slider.value = source.get("default_pages", 5)
        self._detail_slider.value = source.get("default_detail_pages", 0)

        self._start_btn.opacity = 1.0
        self._start_btn.disabled = False
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

        if source["param_key"] == "direct_url":
            job = JobConfig(
                spec_name=source["spec_name"],
                max_pages=int(self._pages_slider.value),
                detail_max_pages=int(self._detail_slider.value),
                direct_urls=[param_value],
            )
        else:
            job = JobConfig(
                spec_name=source["spec_name"],
                max_pages=int(self._pages_slider.value),
                detail_max_pages=int(self._detail_slider.value),
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
