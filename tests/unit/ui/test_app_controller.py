from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.job_config import JobConfig
from ui.app import AppController, main


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
def fake_log_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.setup.return_value = MagicMock()
    return mgr


@pytest.fixture()
def fake_session_manager() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def fake_dispatcher() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def fake_monitor() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def fake_worker() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def ctrl(
    fake_page: MagicMock,
    fake_paths: MagicMock,
    fake_settings: MagicMock,
    fake_log_manager: MagicMock,
    fake_session_manager: MagicMock,
    fake_dispatcher: MagicMock,
    fake_monitor: MagicMock,
    fake_worker: MagicMock,
) -> AppController:
    with patch("ui.app.apply_openpyxl_compat"):
        return AppController(
            page=fake_page,
            paths=fake_paths,
            settings=fake_settings,
            log_manager=fake_log_manager,
            session_manager=fake_session_manager,
            dispatcher=fake_dispatcher,
            monitor=fake_monitor,
            worker_target=fake_worker,
        )


class TestAppControllerConstruction:
    def test_no_bots_import_on_construction(
        self,
        fake_page: MagicMock,
        fake_paths: MagicMock,
        fake_settings: MagicMock,
        fake_log_manager: MagicMock,
        fake_session_manager: MagicMock,
        fake_dispatcher: MagicMock,
        fake_monitor: MagicMock,
    ) -> None:
        sys.modules.pop("bots.universal_bot", None)
        sys.modules.pop("bots", None)

        with patch("ui.app.apply_openpyxl_compat"):
            AppController(
                page=fake_page,
                paths=fake_paths,
                settings=fake_settings,
                log_manager=fake_log_manager,
                session_manager=fake_session_manager,
                dispatcher=fake_dispatcher,
                monitor=fake_monitor,
                worker_target=MagicMock(),
            )

        assert "bots.universal_bot" not in sys.modules
        assert "bots" not in sys.modules

    def test_no_bots_import_on_start_parsing(self, ctrl: AppController) -> None:
        sys.modules.pop("bots.universal_bot", None)
        sys.modules.pop("bots", None)

        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_abc")  # type: ignore[method-assign]

        job = JobConfig(spec_name="habr_search.yaml", max_pages=1, template_params={"keyword": "test"})
        ctrl.start_parsing([job])

        assert "bots.universal_bot" not in sys.modules


class TestStartParsing:
    def test_returns_false_when_running(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=True)  # type: ignore[method-assign]
        job = JobConfig(spec_name="habr_search.yaml")
        result = ctrl.start_parsing([job])
        assert result is False

    def test_returns_false_for_empty_list(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        result = ctrl.start_parsing([])
        assert result is False

    def test_returns_false_when_no_worker_target(
        self,
        fake_page: MagicMock,
        fake_paths: MagicMock,
        fake_settings: MagicMock,
        fake_log_manager: MagicMock,
        fake_session_manager: MagicMock,
        fake_dispatcher: MagicMock,
        fake_monitor: MagicMock,
    ) -> None:
        with patch("ui.app.apply_openpyxl_compat"):
            ctrl_no_worker = AppController(
                page=fake_page,
                paths=fake_paths,
                settings=fake_settings,
                log_manager=fake_log_manager,
                session_manager=fake_session_manager,
                dispatcher=fake_dispatcher,
                monitor=fake_monitor,
                worker_target=None,
            )

        ctrl_no_worker.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        job = JobConfig(spec_name="habr_search.yaml")
        result = ctrl_no_worker.start_parsing([job])
        assert result is False

    def test_returns_true_on_success(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_ok")  # type: ignore[method-assign]
        job = JobConfig(spec_name="habr_search.yaml", max_pages=2, max_records=500)
        result = ctrl.start_parsing([job])
        assert result is True
        assert ctrl.current_session_id == "session_ok"
        assert ctrl.active_specs == ["habr_search.yaml"]
        assert ctrl.active_max_records == 500

    def test_stores_none_when_no_max_records(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_ok")  # type: ignore[method-assign]
        job = JobConfig(spec_name="habr_search.yaml", max_pages=2, max_records=None)
        result = ctrl.start_parsing([job])
        assert result is True
        assert ctrl.active_max_records is None


class TestAppControllerPublicAPI:
    def test_public_attributes_exist(self, ctrl: AppController) -> None:
        assert hasattr(ctrl, "is_running")
        assert hasattr(ctrl, "start_parsing")
        assert hasattr(ctrl, "stop_parsing")
        assert hasattr(ctrl, "cleanup")
        assert hasattr(ctrl, "navigate")
        assert hasattr(ctrl, "theme")
        assert hasattr(ctrl, "monitor")

    def test_is_running_delegates_to_dispatcher(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=True)  # type: ignore[method-assign]
        assert ctrl.is_running() is True
        ctrl.dispatcher.is_running.assert_called_once()

    def test_stop_parsing_calls_stop_all(self, ctrl: AppController) -> None:
        ctrl.stop_parsing()
        ctrl.dispatcher.stop_all.assert_called_once()

    def test_cleanup_stops_everything(self, ctrl: AppController) -> None:
        ctrl.cleanup()
        ctrl.dispatcher.stop_all.assert_called()
        ctrl.log_manager.stop.assert_called_once()


class TestResolveFont:
    def test_returns_fallback_url_for_missing_font(self) -> None:
        from ui.app import _resolve_font

        result = _resolve_font("assets/fonts/Inter-Regular.ttf")
        assert isinstance(result, str)

    def test_returns_path_for_unknown_font(self) -> None:
        from ui.app import _resolve_font

        result = _resolve_font("assets/fonts/NonExistent.ttf")
        assert result == "assets/fonts/NonExistent.ttf"


class TestMainFunction:
    def test_main_is_callable(self) -> None:
        assert callable(main)
