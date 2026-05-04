from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import flet as ft

from ui.app import AppController
from ui.theme import (
    FONT_DISPLAY,
    FONT_MONO,
    FONT_TEXT,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
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

_MONTHS_ABBR = {
    1: "янв",
    2: "фев",
    3: "мар",
    4: "апр",
    5: "мая",
    6: "июн",
    7: "июл",
    8: "авг",
    9: "сен",
    10: "окт",
    11: "ноя",
    12: "дек",
}

_SOURCE_ICONS: dict[str, str] = {
    "reddit": "💬",
    "twogis": "🗺️",
    "steam": "🎮",
    "habr": "📰",
    "lenta": "📡",
    "otzovik": "⭐",
}


def _format_session_date(raw: str) -> str:
    try:
        date_part = raw.split("_")[0] if "_" in raw else raw
        parts = date_part.split("-")
        day = int(parts[2])
        month = int(parts[1])
        return f"{day} {_MONTHS_ABBR.get(month, '???')}"
    except (ValueError, IndexError):
        return raw


def _source_icon(source_name: str) -> str:
    lower = source_name.lower()
    for key, icon in _SOURCE_ICONS.items():
        if key in lower:
            return icon
    return "📊"


def _open_folder(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", str(path)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        logger.debug("Не удалось открыть папку: %s", path)


class ResultsPage:
    """Страница просмотра и экспорта результатов парсинга."""

    def __init__(self, controller: AppController) -> None:
        self._ctrl = controller
        self._sessions_col = ft.Column([], spacing=SPACE_SM)
        self._preview_col = ft.Column([], spacing=SPACE_XS, scroll=ft.ScrollMode.AUTO)

    def build(self) -> ft.Control:
        t = self._ctrl.theme.tokens

        refresh_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.REFRESH, size=SIZE_LABEL, color=t.text_secondary),
                    ft.Text(
                        "Обновить",
                        size=SIZE_LABEL,
                        color=t.text_secondary,
                        font_family=FONT_TEXT,
                    ),
                ],
                spacing=SPACE_XS,
            ),
            border_radius=RADIUS_SM,
            border=ft.Border.all(1, t.border_light),
            padding=ft.Padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=lambda e: self._load_sessions(),
            ink=True,
            bgcolor=t.bg_elevated,
        )

        sessions_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                "Сессии",
                                size=SIZE_HEADING,
                                weight=ft.FontWeight.W_600,
                                color=t.text_primary,
                                font_family=FONT_DISPLAY,
                            ),
                            refresh_btn,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[self._sessions_col],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=320,
                        bgcolor=t.bg_primary,
                        border_radius=RADIUS_SM,
                        padding=SPACE_SM,
                    ),
                ],
                spacing=SPACE_MD,
            ),
            bgcolor=t.bg_elevated,
            border_radius=RADIUS_LG,
            padding=SPACE_LG,
            border=ft.Border.all(1, t.border_light),
        )

        preview_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Предпросмотр данных",
                        size=SIZE_HEADING,
                        weight=ft.FontWeight.W_600,
                        color=t.text_primary,
                        font_family=FONT_DISPLAY,
                    ),
                    ft.Text(
                        "Первые 20 записей",
                        size=SIZE_LABEL,
                        color=t.text_tertiary,
                        font_family=FONT_TEXT,
                    ),
                    ft.Container(
                        content=ft.Row(
                            controls=[self._preview_col],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=400,
                        bgcolor=t.bg_primary,
                        border_radius=RADIUS_SM,
                        padding=SPACE_MD,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                ],
                spacing=SPACE_SM,
            ),
            bgcolor=t.bg_elevated,
            border_radius=RADIUS_LG,
            padding=SPACE_LG,
            border=ft.Border.all(1, t.border_light),
        )

        self._load_sessions()

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Результаты",
                        size=SIZE_TITLE,
                        weight=ft.FontWeight.BOLD,
                        color=t.text_primary,
                        font_family=FONT_DISPLAY,
                    ),
                    sessions_panel,
                    preview_panel,
                ],
                spacing=SPACE_MD,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding.symmetric(horizontal=SPACE_XL, vertical=SPACE_LG),
            expand=True,
            bgcolor=t.bg_primary,
        )

    def _load_sessions(self) -> None:
        t = self._ctrl.theme.tokens
        self._sessions_col.controls.clear()
        data_dir = self._ctrl._paths.data_dir

        if not data_dir.exists():
            self._sessions_col.controls.append(
                ft.Text(
                    "Папка data/ не найдена",
                    color=t.text_tertiary,
                    font_family=FONT_TEXT,
                    size=SIZE_LABEL,
                )
            )
            self._ctrl.page.update()
            return

        sessions = sorted(
            [d for d in data_dir.iterdir() if d.is_dir() and d.name.startswith("session_")],
            reverse=True,
        )

        if not sessions:
            self._sessions_col.controls.append(
                ft.Column(
                    [
                        ft.Text(
                            "📭",
                            size=SIZE_TITLE,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            "Результатов пока нет",
                            size=SIZE_HEADING,
                            color=t.text_primary,
                            font_family=FONT_DISPLAY,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            "Запустите сбор данных на странице «Запуск»",
                            size=SIZE_BODY,
                            color=t.text_secondary,
                            font_family=FONT_TEXT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(
                            content=ft.Text(
                                "Перейти к запуску →",
                                size=SIZE_BODY,
                                color=t.accent,
                                font_family=FONT_TEXT,
                            ),
                            on_click=lambda e: self._ctrl.navigate("launcher"),
                            ink=True,
                            border=ft.Border.all(1, t.accent),
                            border_radius=RADIUS_SM,
                            padding=ft.Padding.symmetric(
                                horizontal=SPACE_MD, vertical=SPACE_SM
                            ),
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=SPACE_SM,
                )
            )
        else:
            for session_dir in sessions[:15]:
                self._sessions_col.controls.append(self._build_session_card(session_dir))

        self._ctrl.page.update()

    def _build_session_card(self, session_dir: Path) -> ft.Control:
        t = self._ctrl.theme.tokens
        source_rows: list[ft.Control] = []

        for source_dir in sorted(session_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            jsonl_file = source_dir / f"{source_dir.name}.jsonl"
            if not jsonl_file.exists():
                continue

            count = self._count_records(jsonl_file)
            icon = _source_icon(source_dir.name)

            def _btn(
                label: str,
                color: str,
                sd: Path = source_dir,
                fmt: str = "csv",
            ) -> ft.Container:
                return ft.Container(
                    content=ft.Text(
                        label,
                        size=SIZE_LABEL,
                        color=color,
                        font_family=FONT_TEXT,
                        weight=ft.FontWeight.W_500,
                    ),
                    border=ft.Border.all(1, color),
                    border_radius=RADIUS_SM,
                    padding=ft.Padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
                    on_click=lambda e, s=sd, f=fmt: self._export(s, f),
                    ink=True,
                )

            source_rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(icon, size=SIZE_HEADING),
                            ft.Column(
                                [
                                    ft.Text(
                                        source_dir.name.replace("_", " ").title(),
                                        size=SIZE_LABEL,
                                        weight=ft.FontWeight.W_500,
                                        color=t.text_primary,
                                        font_family=FONT_TEXT,
                                    ),
                                    ft.Text(
                                        f"{count} записей",
                                        size=SIZE_CAPTION,
                                        color=t.text_tertiary,
                                        font_family=FONT_TEXT,
                                    ),
                                ],
                                spacing=SPACE_XS,
                                expand=True,
                            ),
                            ft.Row(
                                [
                                    _btn("CSV", t.accent, source_dir, "csv"),
                                    _btn("Excel", t.accent_info, source_dir, "xlsx"),
                                    ft.Container(
                                        content=ft.Text(
                                            "📂",
                                            size=SIZE_LABEL,
                                        ),
                                        on_click=lambda e, sd=source_dir: _open_folder(sd),
                                        ink=True,
                                        tooltip="Открыть папку",
                                        padding=ft.Padding.symmetric(
                                            horizontal=SPACE_SM, vertical=SPACE_XS
                                        ),
                                        border_radius=RADIUS_SM,
                                    ),
                                    ft.Container(
                                        content=ft.Text(
                                            "Просмотр",
                                            size=SIZE_LABEL,
                                            color=t.text_secondary,
                                            font_family=FONT_TEXT,
                                        ),
                                        border=ft.Border.all(1, t.border_light),
                                        border_radius=RADIUS_SM,
                                        padding=ft.Padding.symmetric(
                                            horizontal=SPACE_SM, vertical=SPACE_XS
                                        ),
                                        on_click=lambda e, jf=jsonl_file: self._preview(jf),
                                        ink=True,
                                    ),
                                ],
                                spacing=SPACE_XS,
                            ),
                        ],
                        spacing=SPACE_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=t.bg_overlay,
                    border_radius=RADIUS_MD,
                    padding=ft.Padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                )
            )

        session_label = session_dir.name.replace("session_", "")
        date_display = _format_session_date(session_label)

        if not source_rows:
            source_rows.append(
                ft.Text(
                    "Нет данных",
                    size=SIZE_LABEL,
                    color=t.text_tertiary,
                    font_family=FONT_TEXT,
                )
            )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.FOLDER_OUTLINED,
                                size=SIZE_LABEL,
                                color=t.text_tertiary,
                            ),
                            ft.Text(
                                date_display,
                                size=SIZE_LABEL,
                                color=t.text_secondary,
                                font_family=FONT_TEXT,
                            ),
                        ],
                        spacing=SPACE_XS,
                    ),
                    *source_rows,
                ],
                spacing=SPACE_SM,
            ),
            border_radius=RADIUS_MD,
            padding=SPACE_MD,
            border=ft.Border.all(1, t.border_light),
        )

    def _count_records(self, jsonl_file: Path) -> int:
        try:
            count = 0
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        count += 1
            return count
        except OSError:
            return 0

    def _export(self, source_dir: Path, fmt: str) -> None:
        t = self._ctrl.theme.tokens
        try:
            output = self._ctrl.export_data(source_dir, fmt)
            if output:
                self._show_snack(f"Файл сохранён: {output}", t.success)
            else:
                self._show_snack("Нет данных для экспорта", t.accent_warn)
        except Exception as e:
            logger.error("Ошибка экспорта: %s", e)
            self._show_snack("Не удалось экспортировать данные", t.accent_danger)

    def _preview(self, jsonl_file: Path) -> None:
        t = self._ctrl.theme.tokens
        self._preview_col.controls.clear()

        try:
            records: list[dict[str, Any]] = []
            with open(jsonl_file, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    if line.strip():
                        records.append(json.loads(line))

            if not records:
                self._preview_col.controls.append(
                    ft.Text(
                        "Файл пустой",
                        color=t.text_tertiary,
                        font_family=FONT_TEXT,
                    )
                )
            else:
                all_keys: list[str] = []
                seen: set[str] = set()
                for rec in records:
                    for k in rec:
                        if k not in seen and k not in ("metadata", "external_id"):
                            all_keys.append(k)
                            seen.add(k)

                col_width = 180

                header_cells = [
                    ft.Text(
                        "#",
                        size=SIZE_CAPTION,
                        color=t.text_tertiary,
                        font_family=FONT_MONO,
                        width=28,
                        weight=ft.FontWeight.W_500,
                    )
                ]
                for k in all_keys:
                    header_cells.append(
                        ft.Text(
                            k,
                            size=SIZE_CAPTION,
                            weight=ft.FontWeight.W_600,
                            color=t.accent,
                            font_family=FONT_MONO,
                            width=col_width,
                        )
                    )
                self._preview_col.controls.append(
                    ft.Row(list[ft.Control](header_cells), spacing=SPACE_SM)
                )
                self._preview_col.controls.append(ft.Divider(color=t.border, height=1))

                for i, rec in enumerate(records):
                    bg = t.bg_elevated if i % 2 == 0 else "transparent"
                    cells = [
                        ft.Text(
                            str(i + 1),
                            size=SIZE_CAPTION,
                            color=t.text_tertiary,
                            font_family=FONT_MONO,
                            width=28,
                        )
                    ]
                    for k in all_keys:
                        val = str(rec.get(k, ""))
                        display = val[:40] + "..." if len(val) > 40 else val
                        cells.append(
                            ft.Text(
                                display,
                                size=SIZE_CAPTION,
                                color=t.text_secondary,
                                font_family=FONT_MONO,
                                width=col_width,
                                selectable=True,
                            )
                        )
                    self._preview_col.controls.append(
                        ft.Container(
                            content=ft.Row(list[ft.Control](cells), spacing=SPACE_SM),
                            bgcolor=bg,
                            border_radius=RADIUS_SM,
                            padding=ft.Padding.symmetric(horizontal=SPACE_XS, vertical=SPACE_XS),
                        )
                    )

        except (json.JSONDecodeError, OSError):
            self._preview_col.controls.append(
                ft.Text(
                    "Не удалось прочитать файл данных",
                    color=t.accent_danger,
                    font_family=FONT_TEXT,
                )
            )

        self._ctrl.page.update()

    def _show_snack(self, message: str, bgcolor: str) -> None:
        self._ctrl.page.snack_bar = ft.SnackBar(  # type: ignore[attr-defined]
            content=ft.Text(
                message,
                color="#FFFFFF",
                font_family=FONT_TEXT,
            ),
            bgcolor=bgcolor,
        )
        self._ctrl.page.snack_bar.open = True  # type: ignore[attr-defined]
        self._ctrl.page.update()
