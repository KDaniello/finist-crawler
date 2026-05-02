# ruff: noqa: RUF002

from __future__ import annotations

import logging
import logging.handlers
import multiprocessing
import queue
import sys
import threading
import traceback
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]

__all__ = [
    "LogManager",
    "setup_worker_logging",
]


class AsyncDiscordHandler(logging.Handler):
    """
    Асинхронный хендлер для Discord.
    Инкапсулирует свою внутреннюю очередь и поток, не засоряя глобальное пространство.
    """

    def __init__(self, webhook_url: str, app_name: str) -> None:
        super().__init__()
        self.webhook_url = webhook_url
        self.app_name = app_name
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._stop_event = threading.Event()

        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="DiscordLogWorker"
        )
        self._thread.start()

    def _worker_loop(self) -> None:
        """Фоновый цикл отправки логов. Завершается при получении None."""
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            try:
                requests.post(self.webhook_url, json=item, timeout=5)
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def emit(self, record: logging.LogRecord) -> None:
        if not self.webhook_url or record.levelno < logging.ERROR:
            return

        try:
            fields: list[dict[str, str | bool]] = [
                {"name": "Module", "value": record.module, "inline": True},
                {"name": "Process", "value": record.processName or "", "inline": True},
            ]
            if record.exc_info:
                tb = "".join(traceback.format_exception(*record.exc_info))
                fields.append(
                    {"name": "Traceback", "value": f"```{tb[-1000:]}```", "inline": False}
                )

            embed: dict[str, Any] = {
                "title": f"🚨 {record.levelname}: {self.app_name}",
                "description": f"**Msg:** {record.getMessage()}",
                "color": 0xFF0000,
                "fields": fields,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            self._queue.put({"embeds": [embed]})
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Корректное завершение потока при закрытии приложения."""
        self._stop_event.set()
        self._queue.put(None)
        self._thread.join(timeout=2.0)
        super().close()


def _handle_exceptions(
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    exc_traceback: types.TracebackType | None,
) -> None:
    """Глобальный перехватчик критических ошибок."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)  # type: ignore[arg-type]
        return
    logging.critical(
        "Критическая необработанная ошибка:", exc_info=(exc_type, exc_value, exc_traceback)  # type: ignore[arg-type]
    )


class LogManager:
    """
    Управление логированием главного процесса.
    Инкапсулирует QueueListener как атрибут экземпляра — без глобального singleton.
    """

    def __init__(self) -> None:
        self._listener: logging.handlers.QueueListener | None = None

    def setup(
        self,
        logs_dir: Path,
        debug: bool = False,
        app_name: str = "Finist Crawler",
        discord_webhook_url: str | None = None,
    ) -> multiprocessing.Queue[logging.LogRecord]:
        """
        Настройка логирования для ГЛАВНОГО процесса (UI/Dispatcher).
        Создает QueueListener, который пишет логи в файл, консоль и Discord.
        Возвращает multiprocessing.Queue, которую нужно передавать воркерам.
        """
        log_queue: multiprocessing.Queue[logging.LogRecord] = multiprocessing.Queue()
        logs_dir.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(processName)-12s | %(name)s | %(message)s"
        )
        level = logging.DEBUG if debug else logging.INFO

        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "finist.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)

        handlers: list[logging.Handler] = [file_handler, stream_handler]

        if discord_webhook_url:
            discord_handler = AsyncDiscordHandler(webhook_url=discord_webhook_url, app_name=app_name)
            discord_handler.setLevel(logging.ERROR)
            handlers.append(discord_handler)

        root = logging.getLogger()
        root.setLevel(level)
        root.handlers = []
        root.addHandler(logging.handlers.QueueHandler(log_queue))

        self._listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)
        self._listener.start()

        sys.excepthook = _handle_exceptions

        return log_queue

    def add_handler(self, handler: logging.Handler) -> bool:
        """
        Добавляет хендлер в активный QueueListener.

        Потокобезопасно. Используется UI для подключения
        кастомных хендлеров после инициализации логгера.

        Args:
            handler: Хендлер для добавления.

        Returns:
            True если хендлер успешно добавлен.
            False если listener не запущен (логгер ещё не инициализирован).
        """
        if self._listener is None:
            return False
        current = list(self._listener.handlers)
        self._listener.handlers = (*current, handler)
        return True

    def stop(self) -> None:
        """Корректное завершение записи логов и освобождение файлов/потоков."""
        if self._listener:
            self._listener.stop()
            for handler in self._listener.handlers:
                handler.close()
            self._listener = None


def setup_worker_logging(log_queue: multiprocessing.Queue[logging.LogRecord], debug: bool = False) -> None:
    """
    Настройка логирования для ВОРКЕРА (запускается в начале каждого нового Process).
    Воркер НЕ трогает файлы, он только перекидывает логи в очередь главного процесса.
    """
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []
    root.addHandler(logging.handlers.QueueHandler(log_queue))
