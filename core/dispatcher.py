from __future__ import annotations

import logging
import multiprocessing
from multiprocessing.context import SpawnProcess
from multiprocessing.synchronize import Lock as LockType
from typing import Any, Protocol

logger = logging.getLogger(__name__)

__all__ = ["Dispatcher", "SessionManagerProtocol", "WorkerCallable"]


class WorkerCallable(Protocol):
    """
    Контракт (Protocol) функции-воркера.
    Гарантирует, что целевая функция принимает строго определенные аргументы.
    """

    def __call__(
        self,
        spec_name: str,
        session_id: str,
        config_overrides: dict[str, Any],
        log_queue: multiprocessing.Queue[Any],
        browser_lock: LockType,
    ) -> None: ...


class SessionManagerProtocol(Protocol):
    """
    Контракт менеджера сессий (Dependency Inversion).
    Диспетчеру не важно, как именно создаются сессии и где лежат файлы,
    ему нужен только метод, возвращающий ID новой сессии.
    """

    def create_session(self) -> str: ...


class Dispatcher:
    """
    Оркестратор процессов.
    Изолирует задачи веб-скрейпинга в отдельные процессы ОС.
    Не содержит глобального состояния. Жизненный цикл управляется из UI.
    """

    def __init__(
        self, session_manager: SessionManagerProtocol, log_queue: multiprocessing.Queue[Any]
    ) -> None:
        # Строго фиксируем контекст spawn для стабильности в PyInstaller и одинакового поведения на всех ОС
        self._ctx = multiprocessing.get_context("spawn")

        self._session_manager = session_manager
        self._log_queue = log_queue

        # Lock создается строго через контекст
        self._browser_lock: LockType = self._ctx.Lock()

        self._active_processes: dict[str, SpawnProcess] = {}
        self._current_session_id: str | None = None

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    def start_tasks(
        self, worker_target: WorkerCallable, specs: list[str], config_overrides: dict[str, Any]
    ) -> str | None:
        """
        Запускает парсинг переданных спецификаций. Каждая спецификация — отдельный процесс.
        """
        clean_specs = [s.strip() for s in specs if s and s.strip()]
        if not clean_specs:
            logger.warning("Нет спецификаций для запуска.")
            return None

        if self.is_running():
            logger.warning("Попытка запустить задачи, когда предыдущие еще работают.")
            return self._current_session_id

        # Делегируем создание сессии зависимому объекту
        self._current_session_id = self._session_manager.create_session()
        logger.info(f"Диспетчер начал сессию: {self._current_session_id}")

        for spec_name in clean_specs:
            try:
                proc = self._ctx.Process(
                    target=worker_target,
                    args=(
                        spec_name,
                        self._current_session_id,
                        config_overrides,
                        self._log_queue,
                        self._browser_lock,
                    ),
                    name=f"Worker-{spec_name}",
                    daemon=True,  # Воркер умрет вместе с главным процессом
                )
                proc.start()
                self._active_processes[spec_name] = proc
                logger.info(f"Запущен процесс для {spec_name} (PID: {proc.pid})")
            except Exception as e:
                logger.error(f"Не удалось запустить процесс для {spec_name}: {e}", exc_info=True)

        return self._current_session_id

    def stop_all(self) -> None:
        """
        Принудительное и элегантное (Graceful) завершение всех воркеров.
        Должно вызываться из UI (например, при нажатии кнопки 'Стоп' или закрытии окна).
        """
        if not self._active_processes:
            return

        logger.info("Остановка всех процессов-воркеров...")

        # Шаг 1: Просим вежливо (SIGTERM)
        for spec, proc in self._active_processes.items():
            if proc.is_alive():
                logger.debug(f"Отправка сигнала завершения: {spec} (PID: {proc.pid})")
                proc.terminate()

        # Шаг 2: Ждем, давая время на сброс буферов и логов
        for _, proc in self._active_processes.items():
            proc.join(timeout=3.0)

        # Шаг 3: Если процесс завис (например, мертвый лок Camoufox), убиваем жестко (SIGKILL)
        for spec, proc in self._active_processes.items():
            if proc.is_alive():
                logger.warning(f"Процесс {spec} не отвечает. Принудительное убийство.")
                proc.kill()

        self._active_processes.clear()
        self._current_session_id = None
        logger.info("Все воркеры успешно остановлены.")

    def is_running(self) -> bool:
        """Проверяет, есть ли живые воркеры, и очищает список от мертвых."""
        dead_specs = [spec for spec, proc in self._active_processes.items() if not proc.is_alive()]

        for spec in dead_specs:
            proc = self._active_processes.pop(spec)
            exitcode = proc.exitcode

            if exitcode == 0:
                logger.info(f"Воркер {spec} успешно завершен.")
            else:
                logger.warning(f"Воркер {spec} завершился с кодом {exitcode}.")

        return len(self._active_processes) > 0
