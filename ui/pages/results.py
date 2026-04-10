from __future__ import annotations

import json
import logging
from pathlib import Path

import flet as ft

from core.file_manager import DataWriter

logger = logging.getLogger(__name__)


class ResultsPage:
    """Страница просмотра и экспорта результатов парсинга."""

    def __init__(self, controller: object) -> None:
        self._ctrl = controller
        self._sessions_col = ft.Column([], spacing=8)
        self._preview_col = ft.Column([], spacing=4, scroll=ft.ScrollMode.AUTO)

    def build(self) -> ft.Control:
        t = self._ctrl.theme.tokens

        refresh_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.REFRESH, size=14, color=t.text_secondary),
                    ft.Text(
                        "Обновить",
                        size=13,
                        color=t.text_secondary,
                        font_family="Inter",
                    ),
                ],
                spacing=6,
            ),
            border_radius=8,
            border=ft.border.all(1, t.border),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            on_click=lambda e: self._load_sessions(),
            ink=True,
            bgcolor=t.bg_secondary,
        )

        # Сессии в прокручиваемом контейнере фиксированной высоты
        sessions_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                "Сессии парсинга",
                                size=24,
                                weight=ft.FontWeight.W_600,
                                color=t.text_primary,
                                font_family="Inter",
                            ),
                            refresh_btn,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # Фиксированная высота + скролл
                    ft.Container(
                        content=ft.Column(
                            controls=[self._sessions_col],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=320,
                        bgcolor=t.bg_primary,
                        border_radius=10,
                        padding=8,
                    ),
                ],
                spacing=12,
            ),
            bgcolor=t.bg_secondary,
            border_radius=16,
            padding=24,
            border=ft.border.all(1, t.border),
        )

        # Предпросмотр — большой, с горизонтальным скроллом
        preview_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Предпросмотр данных",
                        size=18,
                        weight=ft.FontWeight.W_600,
                        color=t.text_primary,
                        font_family="Inter",
                    ),
                    ft.Text(
                        "Первые 20 записей",
                        size=12,
                        color=t.text_muted,
                        font_family="Inter",
                    ),
                    ft.Container(
                        content=ft.Row(
                            controls=[self._preview_col],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=400,
                        bgcolor=t.bg_primary,
                        border_radius=10,
                        padding=16,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                ],
                spacing=10,
            ),
            bgcolor=t.bg_secondary,
            border_radius=16,
            padding=24,
            border=ft.border.all(1, t.border),
        )

        self._load_sessions()

        return ft.Container(
            content=ft.Column(
                [
                    ft.Column(
                        [
                            ft.Text(
                                "Результаты",
                                size=22,
                                weight=ft.FontWeight.BOLD,
                                color=t.text_primary,
                                font_family="Inter",
                            ),
                            ft.Text(
                                "Просмотр и экспорт собранных данных",
                                size=14,
                                color=t.text_secondary,
                                font_family="Inter",
                            ),
                        ],
                        spacing=4,
                    ),
                    sessions_panel,
                    preview_panel,
                ],
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.padding.symmetric(horizontal=32, vertical=28),
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
                    color=t.text_muted,
                    font_family="Inter",
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
                ft.Text(
                    "Нет завершённых сессий",
                    color=t.text_muted,
                    font_family="Inter",
                    size=13,
                )
            )
        else:
            for session_dir in sessions[:15]:
                self._sessions_col.controls.append(self._build_session_card(session_dir))

        self._ctrl.page.update()

    def _build_session_card(self, session_dir: Path) -> ft.Control:
        t = self._ctrl.theme.tokens
        source_rows = []

        for source_dir in sorted(session_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            jsonl_file = source_dir / f"{source_dir.name}.jsonl"
            if not jsonl_file.exists():
                continue

            count = self._count_records(jsonl_file)

            def _btn(label: str, color: str, sd=source_dir, fmt="csv"):
                return ft.Container(
                    content=ft.Text(
                        label,
                        size=12,
                        color=color,
                        font_family="Inter",
                        weight=ft.FontWeight.W_500,
                    ),
                    border=ft.border.all(1, color),
                    border_radius=6,
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    on_click=lambda e, s=sd, f=fmt: self._export(s, f),
                    ink=True,
                )

            source_rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                width=3,
                                height=32,
                                border_radius=2,
                                bgcolor=t.accent,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        source_dir.name,
                                        size=13,
                                        weight=ft.FontWeight.W_500,
                                        color=t.text_primary,
                                        font_family="Inter",
                                    ),
                                    ft.Text(
                                        f"{count} записей",
                                        size=11,
                                        color=t.text_muted,
                                        font_family="Inter",
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                            ft.Row(
                                [
                                    _btn("CSV", t.accent, source_dir, "csv"),
                                    _btn("XLSX", t.accent_info, source_dir, "xlsx"),
                                    ft.Container(
                                        content=ft.Text(
                                            "Просмотр",
                                            size=12,
                                            color=t.text_secondary,
                                            font_family="Inter",
                                        ),
                                        border=ft.border.all(1, t.border),
                                        border_radius=6,
                                        padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                        on_click=lambda e, jf=jsonl_file: self._preview(jf),
                                        ink=True,
                                    ),
                                ],
                                spacing=6,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=t.bg_elevated,
                    border_radius=10,
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                )
            )

        session_label = session_dir.name.replace("session_", "")

        if not source_rows:
            source_rows.append(
                ft.Text(
                    "Нет данных",
                    size=12,
                    color=t.text_muted,
                    font_family="Inter",
                )
            )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.FOLDER_OUTLINED,
                                size=13,
                                color=t.text_muted,
                            ),
                            ft.Text(
                                session_label,
                                size=12,
                                color=t.text_secondary,
                                font_family="Inter",
                            ),
                        ],
                        spacing=6,
                    ),
                    *source_rows,
                ],
                spacing=6,
            ),
            border_radius=12,
            padding=14,
            border=ft.border.all(1, t.border),
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
            session_id = source_dir.parent.name
            writer = DataWriter(
                base_dir=self._ctrl._paths.data_dir,
                session_id=session_id,
                source=source_dir.name,
            )
            output = writer.export(fmt=fmt)
            if output:
                self._show_snack(f"Сохранено: {output.name}", t.accent)
            else:
                self._show_snack("Нет данных для экспорта", t.accent_warn)
        except Exception as e:
            logger.error("Ошибка экспорта: %s", e)
            self._show_snack(f"Ошибка: {e}", t.accent_danger)

    def _preview(self, jsonl_file: Path) -> None:
        """
        Показывает первые 20 записей.
        Все поля кроме metadata и external_id.
        Вертикальный скролл по строкам, горизонтальный по столбцам.
        """
        t = self._ctrl.theme.tokens
        self._preview_col.controls.clear()

        try:
            records: list[dict] = []
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
                        color=t.text_muted,
                        font_family="Inter",
                    )
                )
            else:
                # Все ключи из всех записей (объединяем)
                all_keys: list[str] = []
                seen: set[str] = set()
                for rec in records:
                    for k in rec.keys():
                        if k not in seen and k not in ("metadata", "external_id"):
                            all_keys.append(k)
                            seen.add(k)

                col_width = 180

                # Заголовки
                header_cells = [
                    ft.Text(
                        "#",
                        size=11,
                        color=t.text_muted,
                        font_family="Inter",
                        width=28,
                        weight=ft.FontWeight.W_500,
                    )
                ]
                for k in all_keys:
                    header_cells.append(
                        ft.Text(
                            k,
                            size=11,
                            weight=ft.FontWeight.W_600,
                            color=t.accent,
                            font_family="Inter",
                            width=col_width,
                        )
                    )
                self._preview_col.controls.append(ft.Row(header_cells, spacing=8))
                self._preview_col.controls.append(ft.Divider(color=t.border, height=1))

                # Строки данных
                for i, rec in enumerate(records):
                    bg = t.bg_elevated if i % 2 == 0 else "transparent"
                    cells = [
                        ft.Text(
                            str(i + 1),
                            size=11,
                            color=t.text_muted,
                            font_family="Inter",
                            width=28,
                        )
                    ]
                    for k in all_keys:
                        val = str(rec.get(k, ""))
                        # Обрезаем длинный текст
                        display = val[:40] + "..." if len(val) > 40 else val
                        cells.append(
                            ft.Text(
                                display,
                                size=11,
                                color=t.text_secondary,
                                font_family="Inter",
                                width=col_width,
                                selectable=True,
                            )
                        )
                    self._preview_col.controls.append(
                        ft.Container(
                            content=ft.Row(cells, spacing=8),
                            bgcolor=bg,
                            border_radius=4,
                            padding=ft.padding.symmetric(horizontal=4, vertical=3),
                        )
                    )

        except (json.JSONDecodeError, OSError) as e:
            self._preview_col.controls.append(
                ft.Text(
                    f"Ошибка: {e}",
                    color=t.accent_danger,
                    font_family="Inter",
                )
            )

        self._ctrl.page.update()

    def _show_snack(self, message: str, bgcolor: str) -> None:
        self._ctrl.page.snack_bar = ft.SnackBar(
            content=ft.Text(
                message,
                color="#FFFFFF",
                font_family="Inter",
            ),
            bgcolor=bgcolor,
        )
        self._ctrl.page.snack_bar.open = True
        self._ctrl.page.update()
