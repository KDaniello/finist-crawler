from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.job_config import JobConfig
from ui.pages.launcher import LauncherPage


def _make_source(**overrides):
    base = {
        "spec_name": "test.yaml",
        "title": "Test Source",
        "icon": "T",
        "description": "A test source",
        "tag": "Технологии",
        "param_label": "Keyword",
        "param_hint": "Enter keyword",
        "param_key": "keyword",
        "default_pages": 5,
        "default_detail_pages": 0,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def mock_ctrl() -> MagicMock:
    ctrl = MagicMock()
    ctrl.theme = MagicMock()
    ctrl.theme.tokens = MagicMock()
    ctrl.theme.tokens.accent = "#22C55E"
    ctrl.theme.tokens.accent_danger = "#EF4444"
    ctrl.theme.tokens.accent_warn = "#F59E0B"
    ctrl.theme.tokens.accent_info = "#3B82F6"
    ctrl.theme.tokens.text_primary = "#FFFFFF"
    ctrl.theme.tokens.text_secondary = "#A1A1AA"
    ctrl.theme.tokens.text_muted = "#52525B"
    ctrl.theme.tokens.bg_primary = "#0F0F0F"
    ctrl.theme.tokens.bg_secondary = "#1A1A1A"
    ctrl.theme.tokens.bg_elevated = "#242424"
    ctrl.theme.tokens.bg_input = "#1A1A1A"
    ctrl.theme.tokens.border = "#27272A"
    ctrl.theme.tokens.border_focus = "#22C55E"
    ctrl.is_running.return_value = False
    ctrl.page = MagicMock()
    return ctrl


class TestLauncherPageBuild:
    def test_build_with_sources(self, mock_ctrl: MagicMock) -> None:
        sources = [_make_source(), _make_source(spec_name="other.yaml", title="Other")]
        page = LauncherPage(mock_ctrl, sources)
        control = page.build()
        assert control is not None

    def test_build_with_no_sources(self, mock_ctrl: MagicMock) -> None:
        page = LauncherPage(mock_ctrl, [])
        control = page.build()
        assert control is not None


class TestLauncherCardClick:
    def test_on_card_click_selects_source(self, mock_ctrl: MagicMock) -> None:
        source = _make_source()
        page = LauncherPage(mock_ctrl, [source])
        page.build()

        card = page._cards[0]
        mock_event = MagicMock()
        mock_event.control.data = source
        mock_event.control.border = None
        mock_event.control.bgcolor = None

        page._on_card_click(mock_event)

        assert page._selected_source == source
        mock_ctrl.page.update.assert_called()


class TestLauncherOnStart:
    def test_on_start_no_source(self, mock_ctrl: MagicMock) -> None:
        page = LauncherPage(mock_ctrl, [_make_source()])
        page.build()
        page._selected_source = None
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_not_called()

    def test_on_start_empty_param(self, mock_ctrl: MagicMock) -> None:
        source = _make_source(param_key="keyword")
        page = LauncherPage(mock_ctrl, [source])
        page.build()
        page._selected_source = source
        page._param_field.value = ""
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_called()

    def test_on_start_app_id_not_digit(self, mock_ctrl: MagicMock) -> None:
        source = _make_source(param_key="app_id")
        page = LauncherPage(mock_ctrl, [source])
        page.build()
        page._selected_source = source
        page._param_field.value = "not_a_number"
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_called()

    def test_on_start_direct_url_no_http(self, mock_ctrl: MagicMock) -> None:
        source = _make_source(param_key="direct_url")
        page = LauncherPage(mock_ctrl, [source])
        page.build()
        page._selected_source = source
        page._param_field.value = "no_http_prefix"
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_called()

    def test_on_start_already_running(self, mock_ctrl: MagicMock) -> None:
        mock_ctrl.is_running.return_value = True
        source = _make_source()
        page = LauncherPage(mock_ctrl, [source])
        page.build()
        page._selected_source = source
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_called()

    def test_on_start_direct_url_success(self, mock_ctrl: MagicMock) -> None:
        mock_ctrl.start_parsing.return_value = True
        source = _make_source(param_key="direct_url")
        page = LauncherPage(mock_ctrl, [source])
        page.build()
        page._selected_source = source
        page._param_field.value = "https://example.com/page"
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_called()
        mock_ctrl.page.run_task.assert_called()

    def test_on_start_keyword_success(self, mock_ctrl: MagicMock) -> None:
        mock_ctrl.start_parsing.return_value = True
        source = _make_source(param_key="keyword")
        page = LauncherPage(mock_ctrl, [source])
        page.build()
        page._selected_source = source
        page._param_field.value = "python"
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_called()

    def test_on_start_failure(self, mock_ctrl: MagicMock) -> None:
        mock_ctrl.start_parsing.return_value = False
        source = _make_source(param_key="keyword")
        page = LauncherPage(mock_ctrl, [source])
        page.build()
        page._selected_source = source
        page._param_field.value = "python"
        mock_event = MagicMock()
        page._on_start(mock_event)
        mock_ctrl.page.update.assert_called()
