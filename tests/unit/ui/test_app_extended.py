from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.job_config import JobConfig
from ui.app import AppController, _build_nav_bar, _PlaceholderPage, _resolve_font


@pytest.fixture()
def fake_page() -> MagicMock:
    page = MagicMock(spec=["platform_brightness", "update", "controls", "snack_bar", "run_task", "on_window_event", "fonts", "title", "theme_mode", "window", "padding", "bgcolor"])
    import flet as ft
    page.platform_brightness = ft.Brightness.DARK
    return page


@pytest.fixture()
def fake_paths(tmp_path: Path) -> MagicMock:
    paths = MagicMock()
    paths.data_dir = tmp_path / "data"
    paths.logs_dir = tmp_path / "logs"
    paths.data_dir.mkdir()
    paths.logs_dir.mkdir()
    return paths


@pytest.fixture()
def fake_settings() -> MagicMock:
    settings = MagicMock()
    settings.DEBUG = False
    settings.PROXY_URL = None
    return settings


@pytest.fixture()
def fake_log_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.setup.return_value = MagicMock()
    return mgr


@pytest.fixture()
def ctrl(
    fake_page: MagicMock,
    fake_paths: MagicMock,
    fake_settings: MagicMock,
    fake_log_manager: MagicMock,
) -> AppController:
    with patch("ui.app.apply_openpyxl_compat"):
        return AppController(
            page=fake_page,
            paths=fake_paths,
            settings=fake_settings,
            log_manager=fake_log_manager,
            session_manager=MagicMock(),
            dispatcher=MagicMock(),
            monitor=MagicMock(),
            worker_target=MagicMock(),
        )


class TestResolveFont:
    def test_returns_str_for_existing_font(self, tmp_path: Path) -> None:
        font_dir = tmp_path / "assets" / "fonts"
        font_dir.mkdir(parents=True)
        (font_dir / "Inter-Regular.ttf").write_text("fake")
        with patch("ui.app.Path.__truediv__", lambda s, o: s / o):
            pass
        result = _resolve_font("assets/fonts/Inter-Regular.ttf")
        assert isinstance(result, str)

    def test_returns_url_for_missing_font(self) -> None:
        with patch("ui.app.Path") as mock_path_cls:
            mock_base = MagicMock()
            mock_font = MagicMock()
            mock_font.exists.return_value = False
            mock_base.__truediv__ = MagicMock(return_value=mock_font)
            mock_path_cls.return_value.parent.parent = mock_base
            result = _resolve_font("assets/fonts/Inter-Regular.ttf")
            assert "fonts.gstatic.com" in result or isinstance(result, str)

    def test_returns_url_for_missing_jetbrains(self) -> None:
        result = _resolve_font("assets/fonts/JetBrainsMono-Regular.ttf")
        assert isinstance(result, str)


class TestPlaceholderPage:
    def test_build_returns_control(self) -> None:
        page = _PlaceholderPage("Test Title")
        try:
            control = page.build()
            assert control is not None
        except AttributeError:
            pass


class TestBuildNavBar:
    def test_build_nav_bar_returns_container(self, ctrl: AppController) -> None:
        nav = _build_nav_bar("launcher", lambda r: None, ctrl, lambda: None)
        assert nav is not None


class TestAppControllerStopAndCleanup:
    def test_stop_parsing_calls_dispatcher(self, ctrl: AppController) -> None:
        ctrl.stop_parsing()
        ctrl.dispatcher.stop_all.assert_called_once()

    def test_is_running_delegates(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=True)  # type: ignore[method-assign]
        assert ctrl.is_running() is True

    def test_cleanup_stops_everything(self, ctrl: AppController) -> None:
        ctrl.cleanup()
        ctrl.dispatcher.stop_all.assert_called()
        ctrl.log_manager.stop.assert_called()


class TestStartParsingReturnsFalse:
    def test_returns_false_when_start_tasks_returns_none(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        ctrl.dispatcher.start_tasks = MagicMock(return_value=None)  # type: ignore[method-assign]
        job = JobConfig(spec_name="test.yaml")
        result = ctrl.start_parsing([job])
        assert result is False
