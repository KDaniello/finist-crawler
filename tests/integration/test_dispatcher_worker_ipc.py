import multiprocessing
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.config import ProjectPaths, Settings
from core.dispatcher import Dispatcher, SessionManagerProtocol
from core.logger import LogManager, setup_worker_logging


class DummySessionManager(SessionManagerProtocol):
    def create_session(self) -> str:
        return "session_ipc_123"


def _dummy_ipc_worker(
    spec_name: str,
    session_id: str,
    config_overrides: dict[str, Any],
    log_queue: multiprocessing.Queue,
    browser_lock: Any,
    settings: Any,
    paths: Any,
) -> None:
    setup_worker_logging(log_queue)

    import logging

    logger = logging.getLogger(f"Worker-{spec_name}")

    logger.info(f"Воркер проснулся! Сессия: {session_id}")
    time.sleep(0.5)
    logger.info("Работа завершена. Ухожу в закат.")


def test_dispatcher_and_logging_ipc(tmp_path: Path, browser_lock):
    logs_dir = tmp_path / "logs"

    log_manager = LogManager()
    log_queue = log_manager.setup(logs_dir=logs_dir, debug=True)

    try:
        mock_settings = MagicMock(spec=Settings)
        mock_paths = MagicMock(spec=ProjectPaths)

        session_mgr = DummySessionManager()
        dispatcher = Dispatcher(session_mgr, log_queue)

        session_id = dispatcher.start_tasks(
            worker_target=_dummy_ipc_worker,
            specs=["ipc_test"],
            config_overrides={},
            settings=mock_settings,
            paths=mock_paths,
        )

        assert session_id == "session_ipc_123"
        assert dispatcher.is_running() is True

        timeout = 3.0
        start_time = time.time()
        while dispatcher.is_running():
            if time.time() - start_time > timeout:
                pytest.fail("Таймаут: Воркер не завершился вовремя!")
            time.sleep(0.1)

        assert dispatcher.is_running() is False

    finally:
        log_manager.stop()
        log_queue.close()
        log_queue.cancel_join_thread()

    log_file = logs_dir / "finist.log"
    assert log_file.exists()

    content = log_file.read_text(encoding="utf-8")
    assert "Воркер проснулся! Сессия: session_ipc_123" in content
    assert "Работа завершена. Ухожу в закат." in content
