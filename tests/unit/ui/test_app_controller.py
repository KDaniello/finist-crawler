# tests/unit/ui/test_app_controller.py
"""
Тесты AppController без реального воркера и без bots/.

Ключевая проверка ISSUE-007: AppController не импортирует bots/ ни при каком сценарии.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.job_config import JobConfig
from ui.app import AppController

# ---------------------------------------------------------------------------
# Фейковый воркер — реализует WorkerCallable без импорта bots/
# ---------------------------------------------------------------------------


def _fake_worker(spec_name, session_id, config_overrides, log_queue, browser_lock) -> None:
    """Минимальный воркер для тестов. Ничего не делает."""


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
def fake_session_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.create_session.return_value = "session_test_123"
    return mgr


@pytest.fixture()
def ctrl(fake_page, fake_paths, fake_settings, fake_session_manager) -> AppController:
    with patch("ui.app.setup_main_logging") as mock_log:
        mock_log.return_value = MagicMock()
        return AppController(
            page=fake_page,
            worker_target=_fake_worker,
            paths=fake_paths,
            settings=fake_settings,
            session_manager=fake_session_manager,
        )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestAppControllerDI:
    """ISSUE-007: worker_target передаётся через DI, не импортируется в runtime."""

    def test_worker_target_stored(self, ctrl: AppController) -> None:
        """Воркер сохраняется как атрибут."""
        assert ctrl._worker_target is _fake_worker

    def test_no_bots_import_on_construction(
        self, fake_page, fake_paths, fake_settings, fake_session_manager
    ) -> None:
        """
        Конструктор AppController не импортирует bots.universal_bot.
        Проверяем через patch: если бы импорт был — patch перехватил бы его.
        """
        import sys

        # Убеждаемся что bots.universal_bot не в sys.modules до теста
        sys.modules.pop("bots.universal_bot", None)

        with patch("ui.app.setup_main_logging", return_value=MagicMock()):
            AppController(
                page=fake_page,
                worker_target=_fake_worker,
                paths=fake_paths,
                settings=fake_settings,
                session_manager=fake_session_manager,
            )

        # После конструктора bots.universal_bot всё ещё не загружен
        assert "bots.universal_bot" not in sys.modules

    def test_no_bots_import_on_start_parsing(self, ctrl: AppController) -> None:
        """start_parsing() не импортирует bots.universal_bot."""
        import sys

        sys.modules.pop("bots.universal_bot", None)

        job = JobConfig(
            spec_name="habr_search.yaml",
            max_pages=1,
            template_params={"keyword": "test"},
        )

        # Мокаем dispatcher чтобы не поднимать реальный процесс
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_abc")
        ctrl.dispatcher.is_running = MagicMock(return_value=False)

        ctrl.start_parsing([job])

        assert "bots.universal_bot" not in sys.modules

    def test_start_parsing_passes_worker_to_dispatcher(self, ctrl: AppController) -> None:
        """Dispatcher получает именно тот воркер, что был инжектирован."""
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_xyz")
        ctrl.dispatcher.is_running = MagicMock(return_value=False)

        job = JobConfig(spec_name="steam_reviews.yaml", max_pages=1)
        ctrl.start_parsing([job])

        call_kwargs = ctrl.dispatcher.start_tasks.call_args
        assert call_kwargs.kwargs["worker_target"] is _fake_worker

    def test_start_parsing_returns_false_when_running(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=True)
        job = JobConfig(spec_name="habr_search.yaml")
        result = ctrl.start_parsing([job])
        assert result is False

    def test_start_parsing_returns_false_for_empty_list(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)
        result = ctrl.start_parsing([])
        assert result is False

    def test_start_parsing_returns_true_on_success(self, ctrl: AppController) -> None:
        ctrl.dispatcher.is_running = MagicMock(return_value=False)
        ctrl.dispatcher.start_tasks = MagicMock(return_value="session_ok")
        job = JobConfig(spec_name="habr_search.yaml", max_pages=2)
        result = ctrl.start_parsing([job])
        assert result is True
        assert ctrl.current_session_id == "session_ok"
        assert ctrl.active_specs == ["habr_search.yaml"]


class TestAppControllerPublicAPI:
    """Публичное API контроллера не раскрывает внутренние детали."""

    def test_data_dir_property(self, ctrl: AppController, fake_paths) -> None:
        """data_dir доступен через property, не через _paths."""
        assert ctrl.data_dir == fake_paths.data_dir

    def test_make_writer_returns_data_writer(self, ctrl: AppController, fake_paths) -> None:
        """make_writer создаёт DataWriter с правильными путями."""
        from core.file_manager import DataWriter

        writer = ctrl.make_writer(session_id="session_test", source="habr_articles")
        assert isinstance(writer, DataWriter)
        assert writer.session_id == "session_test"
        assert writer.source == "habr_articles"

    def test_no_direct_paths_access_needed(self, ctrl: AppController) -> None:
        """Проверяем что _paths не нужно использовать снаружи."""
        # Всё что нужно UI — доступно через публичное API
        assert hasattr(ctrl, "data_dir")  # вместо ctrl._paths.data_dir
        assert hasattr(ctrl, "make_writer")  # вместо DataWriter(ctrl._paths.data_dir, ...)
        assert hasattr(ctrl, "is_running")
        assert hasattr(ctrl, "start_parsing")
        assert hasattr(ctrl, "stop_parsing")
        assert hasattr(ctrl, "cleanup")
        assert hasattr(ctrl, "navigate")
        assert hasattr(ctrl, "theme")
        assert hasattr(ctrl, "monitor")


class TestBuildApp:
    """build_app() возвращает корректную фабрику."""

    def test_build_app_returns_callable(self) -> None:
        from ui.app import build_app

        result = build_app(_fake_worker)
        assert callable(result)

    def test_build_app_accepts_worker_callable(self) -> None:
        """Принимает любую реализацию WorkerCallable."""
        from ui.app import build_app

        def another_worker(spec_name, session_id, config_overrides, log_queue, browser_lock):
            pass

        result = build_app(another_worker)
        assert callable(result)
