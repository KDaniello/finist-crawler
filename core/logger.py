import logging
import logging.handlers
import multiprocessing
import queue
import sys
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path

import requests

__all__ = [
    "add_handler_to_listener",
    "setup_main_logging",
    "setup_worker_logging",
    "stop_main_logging",
]

# Глобальный слушатель для главного процесса
_log_listener: logging.handlers.QueueListener | None = None


class AsyncDiscordHandler(logging.Handler):
    """
    Асинхронный хендлер для Discord.
    Инкапсулирует свою внутреннюю очередь и поток, не засоряя глобальное пространство.
    """

    def __init__(self, webhook_url: str, app_name: str):
        super().__init__()
        self.webhook_url = webhook_url
        self.app_name = app_name
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

        # Запускаем локальный воркер
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="DiscordLogWorker"
        )
        self._thread.start()

    def _worker_loop(self) -> None:
        """Фоновый цикл отправки логов. Завершается при получении None."""
        while not self._stop_event.is_set():
            try:
                # Ждем 1 секунду, чтобы регулярно проверять _stop_event
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:  # Sentinel-значение для остановки
                self._queue.task_done()
                break

            try:
                requests.post(self.webhook_url, json=item, timeout=5)
            except Exception:
                pass  # Логгер не должен ломать приложение при ошибках сети
            finally:
                self._queue.task_done()

    def emit(self, record: logging.LogRecord) -> None:
        if not self.webhook_url or record.levelno < logging.ERROR:
            return

        try:
            embed = {
                "title": f"🚨 {record.levelname}: {self.app_name}",
                "description": f"**Msg:** {record.getMessage()}",
                "color": 0xFF0000,
                "fields": [
                    {"name": "Module", "value": record.module, "inline": True},
                    {"name": "Process", "value": record.processName, "inline": True},
                ],
                "timestamp": datetime.now(UTC).isoformat(),
            }
            if record.exc_info:
                tb = "".join(traceback.format_exception(*record.exc_info))
                embed["fields"].append(
                    {"name": "Traceback", "value": f"```{tb[-1000:]}```", "inline": False}
                )

            self._queue.put({"embeds": [embed]})
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Корректное завершение потока при закрытии приложения."""
        self._stop_event.set()
        self._queue.put(None)
        self._thread.join(timeout=2.0)
        super().close()


def _handle_exceptions(exc_type, exc_value, exc_traceback) -> None:
    """Глобальный перехватчик критических ошибок."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical(
        "Критическая необработанная ошибка:", exc_info=(exc_type, exc_value, exc_traceback)
    )


def setup_main_logging(
    logs_dir: Path,
    debug: bool = False,
    app_name: str = "Finist Crawler",
    discord_webhook_url: str | None = None,
) -> multiprocessing.Queue:
    """
    Настройка логирования для ГЛАВНОГО процесса (UI/Dispatcher).
    Создает QueueListener, который пишет логи в файл, консоль и Discord.
    Возвращает multiprocessing.Queue, которую нужно передавать воркерам.
    """
    global _log_listener

    # Очередь для межпроцессного взаимодействия (MP-safe)
    log_queue = multiprocessing.Queue()
    logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(processName)-12s | %(name)s | %(message)s"
    )
    level = logging.DEBUG if debug else logging.INFO

    # 1. Файловый хендлер
    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "finist.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # 2. Консольный хендлер
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    handlers: list[logging.Handler] = [file_handler, stream_handler]

    # 3. Discord хендлер
    if discord_webhook_url:
        discord_handler = AsyncDiscordHandler(webhook_url=discord_webhook_url, app_name=app_name)
        discord_handler.setLevel(logging.ERROR)
        handlers.append(discord_handler)

    # Настраиваем корневой логгер главного процесса (пишет только в очередь!)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []
    root.addHandler(logging.handlers.QueueHandler(log_queue))

    # Запускаем слушателя, который физически пишет в файлы и сеть
    _log_listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)
    _log_listener.start()

    sys.excepthook = _handle_exceptions

    return log_queue


def setup_worker_logging(log_queue: multiprocessing.Queue, debug: bool = False) -> None:
    """
    Настройка логирования для ВОРКЕРА (запускается в начале каждого нового Process).
    Воркер НЕ трогает файлы, он только перекидывает логи в очередь главного процесса.
    """
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []
    root.addHandler(logging.handlers.QueueHandler(log_queue))


def add_handler_to_listener(handler: logging.Handler) -> bool:
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
    global _log_listener
    if _log_listener is None:
        return False
    current = list(_log_listener.handlers)
    _log_listener.handlers = tuple(current + [handler])
    return True


def stop_main_logging() -> None:
    """Корректное завершение записи логов и освобождение файлов/потоков."""
    global _log_listener
    if _log_listener:
        _log_listener.stop()
        for handler in _log_listener.handlers:
            handler.close()
        _log_listener = None
