# tests/unit/ui/test_app_controller.py
"""
Tests for AppController — current API (page-only constructor).

Invariant: tests never import bots/ directly.
bots.universal_bot is injected via sys.modules patch where needed.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.job_config import JobConfig
from ui.app import AppController, main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_page() -> MagicMock:
    page = MagicMock(spec=["platform_brightness", "update", "controls", "snack_bar"])
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
def ctrl(fake_page: MagicMock, fake_paths: MagicMock, fake_settings: MagicMock) -> AppController:
    with (
        patch("ui.app.get_paths", return_value=fake_paths),
        patch("ui.app.get_settings", return_value=fake_settings),
        patch("ui.app.apply_openpyxl_compat"),
        patch("ui.app.LogManager") as mock_log_mgr_cls,
        patch("ui.app.SessionManager"),
        patch("ui.app.Dispatcher"),
        patch("ui.app.SystemMonitor"),
    ):
        mock_log_mgr_cls.return_value.setup.return_value = MagicMock()
        return AppController(page=fake_page)


@pytest.fixture()
def bot_mock() -> Generator[MagicMock]:
    fake_module = MagicMock()
    with patch.dict(sys.modules, {"bots": fake_module, "bots.universal_bot": fake_module}):
        yield fake_module


# ---------------------------------------------------------------------------
# TestAppControllerConstruction
# ---------------------------------------------------------------------------


class TestAppControllerConstruction:
    def test_no_bots_import_on_construction(
        self, fake_page: MagicMock, fake_paths: MagicMock, fake_settings: MagicMock
    ) -> None:
        sys.modules.pop("bots.universal_bot", None)
        sys.modules.pop("bots", None)

        with (
            patch("ui.app.get_paths", return_value=fake_paths),
            patch("ui.app.get_settings", return_value=fake_settings),
            patch("ui.app.apply_openpyxl_compat"),
            patch("ui.app.LogManager") as mock_log_mgr_cls,
            patch("ui.app.SessionManager"),
            patch("ui.app.Dispatcher"),
            patch("ui.app.SystemMonitor"),
        ):
            mock_log_mgr_cls.return_value.setup.return_value = MagicMock()
            AppController(page=fake_page)

        assert "bots.universal_bot" not in sys.modules
        assert "bots" not in sys.modules

    @pytest.mark.xfail(reason="start_parsing imports bots.universal_bot — fix in T5.2")
    def test_no_bots_import_on_start_parsing(self, ctrl: AppController) -> None:
        sys.modules.pop("bots.universal_bot", None)
        sys.modules.pop("bots", None)

        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_abc")  # type: ignore[method-assign]

        job = JobConfig(spec_name="habr_search.yaml", max_pages=1, template_params={"keyword": "test"})
        ctrl.start_parsing([job])

        assert "bots.universal_bot" not in sys.modules


# ---------------------------------------------------------------------------
# TestStartParsing
# ---------------------------------------------------------------------------


class TestStartParsing:
    def test_returns_false_when_running(self, ctrl: AppController, bot_mock: MagicMock) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=True)  # type: ignore[method-assign]
        job = JobConfig(spec_name="habr_search.yaml")
        result = ctrl.start_parsing([job])
        assert result is False

    def test_returns_false_for_empty_list(self, ctrl: AppController, bot_mock: MagicMock) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        result = ctrl.start_parsing([])
        assert result is False

    def test_returns_true_on_success(self, ctrl: AppController, bot_mock: MagicMock) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_ok")  # type: ignore[method-assign]
        job = JobConfig(spec_name="habr_search.yaml", max_pages=2)
        result = ctrl.start_parsing([job])
        assert result is True
        assert ctrl.current_session_id == "session_ok"
        assert ctrl.active_specs == ["habr_search.yaml"]


# ---------------------------------------------------------------------------
# TestAppControllerPublicAPI
# ---------------------------------------------------------------------------


class TestAppControllerPublicAPI:
    def test_public_attributes_exist(self, ctrl: AppController) -> None:
        assert hasattr(ctrl, "is_running")
        assert hasattr(ctrl, "start_parsing")
        assert hasattr(ctrl, "stop_parsing")
        assert hasattr(ctrl, "cleanup")
        assert hasattr(ctrl, "navigate")
        assert hasattr(ctrl, "theme")
        assert hasattr(ctrl, "monitor")


# ---------------------------------------------------------------------------
# TestMainFunction
# ---------------------------------------------------------------------------


class TestMainFunction:
    def test_main_is_callable(self) -> None:
        assert callable(main)
