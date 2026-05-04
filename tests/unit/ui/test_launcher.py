from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ui.pages.launcher import LauncherPage


def _make_source(**overrides: object) -> dict[str, object]:
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
    ctrl.theme.tokens.bg_input = "#2C2C2E"
    ctrl.theme.tokens.bg_overlay = "#343436"
    ctrl.theme.tokens.border = "#38383A"
    ctrl.theme.tokens.border_focus = "#0A84FF"
    ctrl.theme.tokens.border_light = "#38383A"
    ctrl.theme.tokens.accent_light = "#1C3A5C"
    ctrl.theme.tokens.neutral = "#8E8E93"
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

        page._cards[0]
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
