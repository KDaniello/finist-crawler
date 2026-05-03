"""
Tests for bots/universal_bot.py

Coverage: 100%
- Worker logging setup.
- Successful bot run: correct dependency injection into classes.
- save_records closure: saving a batch, ignoring empty list.
- Default source_key (stripping .yaml from filename).
- asyncio.CancelledError handling (graceful stop).
- Global Exception handling (critical failure).
- KeyboardInterrupt suppression via contextlib.
"""

import asyncio
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from bots.universal_bot import run_universal_bot


@pytest.fixture
def mock_deps():
    with (
        patch("bots.universal_bot.setup_worker_logging") as m_log,
        patch("bots.universal_bot.load_spec") as m_load,
        patch("bots.universal_bot.build_plan") as m_build,
        patch("bots.universal_bot.DataWriter") as m_writer,
        patch("bots.universal_bot.FallbackOrchestrator") as m_orch,
    ):
        m_settings = MagicMock()
        m_settings.PROXY_URL = "http://proxy"

        m_paths = MagicMock()
        m_paths.specs_dir = "/fake/specs"
        m_paths.data_dir = "/fake/data"
        m_paths.profiles_dir = Path("/fake/profiles")

        m_load.return_value = {"source_key": "custom_domain"}

        m_plan = MagicMock()
        m_plan.render_strategy = "auto"
        m_plan.start_urls = ["http://test"]
        m_build.return_value = m_plan

        m_writer_inst = MagicMock()
        m_writer.return_value = m_writer_inst

        m_orch_inst = MagicMock()
        m_orch_inst.execute_plan = AsyncMock(return_value=(10, {"pages": 1}))
        m_orch.return_value = m_orch_inst

        yield {
            "log": m_log,
            "settings": m_settings,
            "paths": m_paths,
            "load": m_load,
            "build": m_build,
            "writer": m_writer,
            "writer_inst": m_writer_inst,
            "orch": m_orch,
            "orch_inst": m_orch_inst,
            "plan": m_plan,
        }


class TestUniversalBot:
    def test_run_success_and_callback(self, mock_deps, caplog):
        log_queue = MagicMock()
        browser_lock = MagicMock()

        run_universal_bot(
            "test.yaml",
            "sess_123",
            {"max_pages": 5},
            log_queue,
            browser_lock,
            mock_deps["settings"],
            mock_deps["paths"],
        )

        mock_deps["log"].assert_called_once_with(log_queue)

        mock_deps["load"].assert_called_once_with("test.yaml", "/fake/specs")
        mock_deps["build"].assert_called_once_with(
            {"source_key": "custom_domain"}, {"max_pages": 5}
        )

        mock_deps["writer"].assert_called_once_with(
            base_dir="/fake/data",
            session_id="sess_123",
            source="custom_domain",
            lock=ANY,
        )

        mock_deps["orch"].assert_called_once_with(
            browser_lock=browser_lock,
            profiles_dir=Path("/fake/profiles"),
            render_strategy="auto",
        )
        mock_deps["orch_inst"].execute_plan.assert_called_once()

        kwargs = mock_deps["orch_inst"].execute_plan.call_args.kwargs
        assert kwargs["plan"] == mock_deps["plan"]
        assert kwargs["proxy_url"] == "http://proxy"

        save_cb = kwargs["save_cb"]

        save_cb([])
        mock_deps["writer_inst"].save_batch.assert_not_called()

        save_cb([{"id": 1}])
        mock_deps["writer_inst"].save_batch.assert_called_once_with([{"id": 1}])

        assert "successfully" in caplog.text.lower() or "успешно завершен" in caplog.text

    def test_default_source_key(self, mock_deps):
        mock_deps["load"].return_value = {}

        run_universal_bot(
            "reddit.yaml",
            "sess_123",
            {},
            MagicMock(),
            MagicMock(),
            mock_deps["settings"],
            mock_deps["paths"],
        )

        mock_deps["writer"].assert_called_once_with(
            base_dir="/fake/data",
            session_id="sess_123",
            source="reddit",
            lock=ANY,
        )

    def test_run_cancelled_error(self, mock_deps, caplog):
        mock_deps["orch_inst"].execute_plan.side_effect = asyncio.CancelledError()

        run_universal_bot(
            "test.yaml",
            "sess_123",
            {},
            MagicMock(),
            MagicMock(),
            mock_deps["settings"],
            mock_deps["paths"],
        )

        assert "принудительно остановлен пользователем" in caplog.text
        assert "завершает работу" in caplog.text

    def test_run_general_exception(self, mock_deps, caplog):
        mock_deps["build"].side_effect = ValueError("Broken YAML structure")

        run_universal_bot(
            "test.yaml",
            "sess_123",
            {},
            MagicMock(),
            MagicMock(),
            mock_deps["settings"],
            mock_deps["paths"],
        )

        assert "Критическая ошибка в боте" in caplog.text
        assert "Broken YAML structure" in caplog.text
        assert "завершает работу" in caplog.text

    @patch("asyncio.run")
    def test_run_keyboard_interrupt(self, mock_asyncio_run, mock_deps):
        mock_asyncio_run.side_effect = KeyboardInterrupt()

        run_universal_bot(
            "test.yaml",
            "sess_123",
            {},
            MagicMock(),
            MagicMock(),
            mock_deps["settings"],
            mock_deps["paths"],
        )
        mock_asyncio_run.assert_called_once()
