from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ui.pages.results import ResultsPage


@pytest.fixture()
def mock_ctrl(tmp_path: Path) -> MagicMock:
    ctrl = MagicMock()
    ctrl.theme = MagicMock()
    ctrl.theme.tokens = MagicMock()
    ctrl.theme.tokens.accent = "#0A84FF"
    ctrl.theme.tokens.accent_danger = "#FF453A"
    ctrl.theme.tokens.accent_warn = "#FF9F0A"
    ctrl.theme.tokens.accent_info = "#0A84FF"
    ctrl.theme.tokens.text_primary = "#FFFFFF"
    ctrl.theme.tokens.text_secondary = "#EBEBF5"
    ctrl.theme.tokens.text_muted = "#636366"
    ctrl.theme.tokens.text_tertiary = "#48484A"
    ctrl.theme.tokens.bg_primary = "#1C1C1E"
    ctrl.theme.tokens.bg_secondary = "#2C2C2E"
    ctrl.theme.tokens.bg_elevated = "#3A3A3C"
    ctrl.theme.tokens.bg_overlay = "#343436"
    ctrl.theme.tokens.border = "#38383A"
    ctrl.theme.tokens.border_light = "#38383A"
    ctrl.page = MagicMock()
    ctrl._paths = MagicMock()
    ctrl._paths.data_dir = tmp_path / "data"
    ctrl._paths.data_dir.mkdir()
    return ctrl


def _create_session_data(data_dir: Path, session_name: str, source_name: str, records: list[dict[str, object]]) -> None:
    session_dir = data_dir / session_name
    source_dir = session_dir / source_name
    source_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = source_dir / f"{source_name}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class TestResultsPageBuild:
    def test_build_with_sessions(self, mock_ctrl: MagicMock) -> None:
        data_dir = mock_ctrl._paths.data_dir
        _create_session_data(data_dir, "session_2024-01-01", "reddit", [{"id": 1, "text": "hello"}])
        page = ResultsPage(mock_ctrl)
        control = page.build()
        assert control is not None
        mock_ctrl.page.update.assert_called()

    def test_build_no_data_dir(self, mock_ctrl: MagicMock, tmp_path: Path) -> None:
        mock_ctrl._paths.data_dir = tmp_path / "nonexistent"
        page = ResultsPage(mock_ctrl)
        control = page.build()
        assert control is not None

    def test_build_empty_data_dir(self, mock_ctrl: MagicMock) -> None:
        page = ResultsPage(mock_ctrl)
        control = page.build()
        assert control is not None


class TestResultsCountRecords:
    def test_count_records(self, mock_ctrl: MagicMock) -> None:
        data_dir = mock_ctrl._paths.data_dir
        _create_session_data(data_dir, "session_1", "test_src", [
            {"id": 1}, {"id": 2}, {"id": 3},
        ])
        page = ResultsPage(mock_ctrl)
        jsonl = data_dir / "session_1" / "test_src" / "test_src.jsonl"
        assert page._count_records(jsonl) == 3

    def test_count_records_os_error(self, mock_ctrl: MagicMock) -> None:
        page = ResultsPage(mock_ctrl)
        result = page._count_records(Path("/nonexistent/file.jsonl"))
        assert result == 0


class TestResultsPreview:
    def test_preview_valid_data(self, mock_ctrl: MagicMock) -> None:
        data_dir = mock_ctrl._paths.data_dir
        records = [{"id": i, "text": f"Row {i}"} for i in range(25)]
        _create_session_data(data_dir, "session_1", "test_src", records)
        page = ResultsPage(mock_ctrl)
        page.build()

        jsonl = data_dir / "session_1" / "test_src" / "test_src.jsonl"
        page._preview(jsonl)
        assert len(page._preview_col.controls) > 0

    def test_preview_empty_file(self, mock_ctrl: MagicMock) -> None:
        data_dir = mock_ctrl._paths.data_dir
        _create_session_data(data_dir, "session_1", "test_src", [])
        page = ResultsPage(mock_ctrl)
        page.build()

        jsonl = data_dir / "session_1" / "test_src" / "test_src.jsonl"
        page._preview(jsonl)
        assert len(page._preview_col.controls) > 0

    def test_preview_invalid_json(self, mock_ctrl: MagicMock) -> None:
        data_dir = mock_ctrl._paths.data_dir
        session_dir = data_dir / "session_1" / "bad_src"
        session_dir.mkdir(parents=True)
        jsonl = session_dir / "bad_src.jsonl"
        jsonl.write_text("not valid json{{{", encoding="utf-8")

        page = ResultsPage(mock_ctrl)
        page.build()
        page._preview(jsonl)
        assert len(page._preview_col.controls) > 0


class TestResultsExport:
    def test_export_csv(self, mock_ctrl: MagicMock) -> None:
        data_dir = mock_ctrl._paths.data_dir
        _create_session_data(data_dir, "session_1", "test_src", [{"id": 1, "text": "hi"}])
        page = ResultsPage(mock_ctrl)
        page.build()

        source_dir = data_dir / "session_1" / "test_src"
        page._export(source_dir, "csv")
        mock_ctrl.page.update.assert_called()

    def test_export_no_data(self, mock_ctrl: MagicMock) -> None:
        data_dir = mock_ctrl._paths.data_dir
        session_dir = data_dir / "session_empty" / "empty_src"
        session_dir.mkdir(parents=True)

        page = ResultsPage(mock_ctrl)
        page.build()
        source_dir = data_dir / "session_empty" / "empty_src"
        page._export(source_dir, "csv")
        mock_ctrl.page.update.assert_called()


class TestResultsShowSnack:
    def test_show_snack(self, mock_ctrl: MagicMock) -> None:
        page = ResultsPage(mock_ctrl)
        page._show_snack("Test message", "#30D158")
        mock_ctrl.page.update.assert_called()
