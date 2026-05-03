import multiprocessing
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from core.config import ProjectPaths, Settings
from core.dispatcher import Dispatcher, SessionManagerProtocol
from core.logger import LogManager


class DummySessionManager(SessionManagerProtocol):
    def create_session(self) -> str:
        return "stress_session_kill"


def _endless_worker(
    spec_name: str,
    session_id: str,
    config_overrides: dict[str, Any],
    log_queue: multiprocessing.Queue,
    browser_lock: Any,
    settings: Any,
    paths: Any,
) -> None:
    import logging

    from core.logger import setup_worker_logging

    setup_worker_logging(log_queue)
    logger = logging.getLogger(f"EndlessWorker-{spec_name}")
    logger.info(f"[{spec_name}] Запущен бесконечный воркер")

    while True:
        time.sleep(0.1)


@pytest.mark.stress
def test_stop_all_leaves_no_orphan_processes(tmp_path: Path):
    logs_dir = tmp_path / "logs"
    log_manager = LogManager()
    log_queue = log_manager.setup(logs_dir=logs_dir, debug=False)

    try:
        real_settings = Settings()
        real_paths = ProjectPaths()

        session_mgr = DummySessionManager()
        dispatcher = Dispatcher(session_mgr, log_queue)

        session_id = dispatcher.start_tasks(
            worker_target=_endless_worker,
            specs=["site_a", "site_b", "site_c"],
            config_overrides={},
            settings=real_settings,
            paths=real_paths,
        )

        assert session_id is not None

        time.sleep(2.0)

        assert dispatcher.is_running() is True

        pids_before = {
            proc.pid for proc in dispatcher._active_processes.values() if proc.pid is not None
        }
        assert len(pids_before) == 3

        dispatcher.stop_all()

        time.sleep(2.0)

        for pid in pids_before:
            assert not psutil.pid_exists(pid), (
                f"Осиротевший процесс PID={pid} всё ещё жив после stop_all()! "
                f"Это утечка процессов ОС."
            )

        assert dispatcher.is_running() is False

    finally:
        log_manager.stop()
        log_queue.close()
        log_queue.cancel_join_thread()
