"""
Стресс-тест: Жесткое уничтожение воркеров пользователем.

Проверяет, что после Dispatcher.stop_all() в системе не остается
осиротевших процессов Python, которые продолжают жрать CPU/RAM.
"""

import multiprocessing
import time
from pathlib import Path
from typing import Any

import psutil

from core.dispatcher import Dispatcher, SessionManagerProtocol
from core.logger import setup_main_logging, stop_main_logging


class DummySessionManager(SessionManagerProtocol):
    def create_session(self) -> str:
        return "stress_session_kill"


def _endless_worker(
    spec_name: str,
    session_id: str,
    config_overrides: dict[str, Any],
    log_queue: multiprocessing.Queue,
    browser_lock: Any,
) -> None:
    """Воркер, который работает бесконечно (симулирует долгий парсинг)."""
    import logging

    from core.logger import setup_worker_logging

    setup_worker_logging(log_queue)
    logger = logging.getLogger(f"EndlessWorker-{spec_name}")
    logger.info(f"[{spec_name}] Запущен бесконечный воркер")

    # Бесконечный цикл — имитируем долгий парсинг
    while True:
        time.sleep(0.1)


def test_stop_all_leaves_no_orphan_processes(tmp_path: Path):
    """
    СЦЕНАРИЙ: Запускаем 3 бесконечных воркера. Вызываем stop_all() (как при закрытии UI).
    ОЖИДАНИЕ: Все дочерние процессы Python мертвы. Нет утечек процессов в ОС.
    """
    logs_dir = tmp_path / "logs"
    log_queue = setup_main_logging(logs_dir=logs_dir, debug=False)

    try:
        session_mgr = DummySessionManager()
        dispatcher = Dispatcher(session_mgr, log_queue)

        # Запускаем 3 воркера параллельно
        session_id = dispatcher.start_tasks(
            worker_target=_endless_worker,
            specs=["site_a", "site_b", "site_c"],
            config_overrides={},
        )

        assert session_id is not None

        # Даём процессам время на старт
        time.sleep(2.0)

        # Проверяем, что все 3 воркера живы
        assert dispatcher.is_running() is True

        # Сохраняем PID-ы до уничтожения
        pids_before = {
            proc.pid for proc in dispatcher._active_processes.values() if proc.pid is not None
        }
        assert len(pids_before) == 3

        # ЖЕСТКАЯ ОСТАНОВКА (симуляция закрытия окна приложения)
        dispatcher.stop_all()

        # Даём ОС 2 секунды на финальную уборку
        time.sleep(2.0)

        # ПРОВЕРКА: Все PID-ы мертвы
        for pid in pids_before:
            assert not psutil.pid_exists(pid), (
                f"Осиротевший процесс PID={pid} всё ещё жив после stop_all()! "
                f"Это утечка процессов ОС."
            )

        assert dispatcher.is_running() is False

    finally:
        stop_main_logging()
        log_queue.close()
        log_queue.cancel_join_thread()
