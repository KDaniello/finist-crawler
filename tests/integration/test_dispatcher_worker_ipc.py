"""
Интеграционный тест межпроцессного взаимодействия (IPC).
Проверяет связку: Dispatcher -> Spawn Process -> QueueHandler -> QueueListener.
"""

import multiprocessing
import time
from pathlib import Path
from typing import Any

import pytest

from core.dispatcher import Dispatcher, SessionManagerProtocol
from core.logger import setup_main_logging, setup_worker_logging, stop_main_logging


class DummySessionManager(SessionManagerProtocol):
    def create_session(self) -> str:
        return "session_ipc_123"


# ВАЖНО: Функция-воркер должна быть на уровне модуля (global),
# чтобы модуль multiprocessing мог её сериализовать (pickle) для контекста 'spawn' в Windows.
def _dummy_ipc_worker(
    spec_name: str,
    session_id: str,
    config_overrides: dict[str, Any],
    log_queue: multiprocessing.Queue,
    browser_lock: Any,
) -> None:
    """Эмулирует работу бота в отдельном процессе."""
    # Настраиваем перехват логов в очередь
    setup_worker_logging(log_queue)

    import logging

    logger = logging.getLogger(f"Worker-{spec_name}")

    logger.info(f"Воркер проснулся! Сессия: {session_id}")
    time.sleep(0.5)  # Имитация работы
    logger.info("Работа завершена. Ухожу в закат.")


def test_dispatcher_and_logging_ipc(tmp_path: Path, browser_lock):
    """
    Проверяет, что:
    1. Логи из изолированного процесса успешно долетают до файла в главном процессе.
    2. Диспетчер корректно отслеживает жизненный цикл (start -> is_running -> stop).
    """
    logs_dir = tmp_path / "logs"

    # 1. Запускаем слушателя логов в главном процессе
    log_queue = setup_main_logging(logs_dir=logs_dir, debug=True)

    try:
        session_mgr = DummySessionManager()
        dispatcher = Dispatcher(session_mgr, log_queue)

        # 2. Запускаем процесс
        session_id = dispatcher.start_tasks(
            worker_target=_dummy_ipc_worker, specs=["ipc_test"], config_overrides={}
        )

        assert session_id == "session_ipc_123"
        assert dispatcher.is_running() is True

        # 3. Ждем завершения процесса (с таймаутом 3 секунды)
        timeout = 3.0
        start_time = time.time()
        while dispatcher.is_running():
            if time.time() - start_time > timeout:
                pytest.fail("Таймаут: Воркер не завершился вовремя!")
            time.sleep(0.1)

        assert dispatcher.is_running() is False

    finally:
        stop_main_logging()
        log_queue.close()
        log_queue.cancel_join_thread()

    # 4. Проверяем, что логи физически записались в файл
    log_file = logs_dir / "finist.log"
    assert log_file.exists()

    content = log_file.read_text(encoding="utf-8")
    assert "Воркер проснулся! Сессия: session_ipc_123" in content
    assert "Работа завершена. Ухожу в закат." in content
