# mypy: disable-error-code=no-untyped-def
# ruff: noqa: RUF003

"""
Тесты для core/logger.py

Покрытие: 100%
- AsyncDiscordHandler: запуск/остановка потока, форматирование traceback, сетевые ошибки,
  handleError, пропуск логов < ERROR, игнорирование пустых очередей.
- LogManager: setup (создание файлов, очередей, интеграция DI), add_handler, stop.
- setup_worker_logging (изоляция QueueHandler).
- Глобальный перехватчик: _handle_exceptions (обработка KeyboardInterrupt и критических сбоев).
"""

import logging
import multiprocessing
import queue
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests  # type: ignore[import-untyped]

import core.logger
from core.logger import (
    AsyncDiscordHandler,
    LogManager,
    _handle_exceptions,
    setup_worker_logging,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_logging():
    """Сбрасывает конфигурацию логгера до и после каждого теста."""
    yield
    root = logging.getLogger()
    root.handlers.clear()
    sys.excepthook = sys.__excepthook__


@pytest.fixture
def dummy_record():
    return logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Тестовая ошибка",
        args=(),
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# AsyncDiscordHandler Tests
# ---------------------------------------------------------------------------


class TestAsyncDiscordHandler:
    def test_emit_skips_below_error(self, dummy_record):
        handler = AsyncDiscordHandler("http://hook", "App")
        dummy_record.levelno = logging.INFO

        handler.emit(dummy_record)
        assert handler._queue.empty()
        handler.close()

    @patch("requests.post")
    def test_emit_sends_error(self, mock_post, dummy_record):
        handler = AsyncDiscordHandler("http://hook", "App")
        handler.emit(dummy_record)

        handler._queue.join()

        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        assert kwargs["timeout"] == 5
        assert "embeds" in kwargs["json"]
        assert "Тестовая ошибка" in kwargs["json"]["embeds"][0]["description"]

        handler.close()

    @patch("requests.post")
    def test_emit_with_traceback(self, mock_post, dummy_record):
        handler = AsyncDiscordHandler("http://hook", "App")

        try:
            _ = 1 / 0
        except ZeroDivisionError:
            dummy_record.exc_info = sys.exc_info()

        handler.emit(dummy_record)
        handler._queue.join()

        payload = mock_post.call_args.kwargs["json"]
        fields = payload["embeds"][0]["fields"]

        assert len(fields) == 3
        assert fields[-1]["name"] == "Traceback"
        assert "ZeroDivisionError" in fields[-1]["value"]

        handler.close()

    @patch("requests.post", side_effect=requests.exceptions.ConnectionError)
    def test_worker_loop_ignores_network_errors(self, mock_post, dummy_record):
        handler = AsyncDiscordHandler("http://hook", "App")
        handler.emit(dummy_record)

        handler._queue.join()
        assert mock_post.call_count == 1
        assert handler._thread.is_alive()

        handler.close()

    def test_emit_handles_internal_errors(self, dummy_record):
        handler = AsyncDiscordHandler("http://hook", "App")

        with (
            patch.object(handler._queue, "put", side_effect=Exception("Queue broken")),
            patch.object(handler, "handleError") as mock_handle_error,
        ):
            handler.emit(dummy_record)
            mock_handle_error.assert_called_once_with(dummy_record)

        handler.close()

    def test_worker_loop_queue_empty(self):
        handler = AsyncDiscordHandler("http://hook", "App")
        handler.close()

        handler._stop_event.clear()

        with (
            patch.object(handler._queue, "get", side_effect=[queue.Empty, None]),
            patch.object(handler._queue, "task_done"),
        ):
            handler._worker_loop()


# ---------------------------------------------------------------------------
# LogManager Tests
# ---------------------------------------------------------------------------


class TestLogManager:
    def test_setup_creates_queue_and_listener(self, tmp_path: Path):
        manager = LogManager()
        q = manager.setup(
            logs_dir=tmp_path,
            debug=True,
            app_name="TestApp",
            discord_webhook_url="http://fake-hook",
        )

        assert manager._listener is not None
        assert isinstance(q, multiprocessing.queues.Queue)

        handlers = manager._listener.handlers
        assert len(handlers) == 3
        assert isinstance(handlers[0], logging.handlers.RotatingFileHandler)
        assert isinstance(handlers[1], logging.StreamHandler)
        assert isinstance(handlers[2], AsyncDiscordHandler)

        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.handlers.QueueHandler)

        manager.stop()

    def test_stop_clears_listener(self, tmp_path: Path):
        manager = LogManager()
        manager.setup(logs_dir=tmp_path, discord_webhook_url="http://hook")

        listener = manager._listener
        assert listener is not None
        discord_handler = listener.handlers[-1]

        manager.stop()

        assert manager._listener is None
        assert not discord_handler._thread.is_alive()

    def test_add_handler_returns_false_when_no_listener(self):
        manager = LogManager()
        handler = logging.StreamHandler()
        assert manager.add_handler(handler) is False

    def test_add_handler_succeeds(self, tmp_path: Path):
        manager = LogManager()
        manager.setup(logs_dir=tmp_path)

        new_handler = logging.StreamHandler()
        result = manager.add_handler(new_handler)

        assert result is True
        assert new_handler in manager._listener.handlers

        manager.stop()


# ---------------------------------------------------------------------------
# Worker Logging Tests
# ---------------------------------------------------------------------------


class TestWorkerLogging:
    def test_setup_worker_logging(self):
        q: multiprocessing.Queue[logging.LogRecord] = multiprocessing.Queue()
        setup_worker_logging(log_queue=q, debug=True)

        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.handlers.QueueHandler)
        assert root.level == logging.DEBUG


# ---------------------------------------------------------------------------
# Exception Handler Tests
# ---------------------------------------------------------------------------


class TestExceptionHook:
    @patch("logging.critical")
    def test_handle_exceptions_generic(self, mock_critical):
        try:
            raise ValueError("Test error")
        except ValueError:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            _handle_exceptions(exc_type, exc_value, exc_traceback)  # type: ignore[arg-type]

        mock_critical.assert_called_once()
        assert "Критическая необработанная ошибка" in mock_critical.call_args.args[0]

    @patch("sys.__excepthook__")
    @patch("logging.critical")
    def test_handle_exceptions_keyboard_interrupt(self, mock_critical, mock_excepthook):
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            _handle_exceptions(exc_type, exc_value, exc_traceback)  # type: ignore[arg-type]

        mock_critical.assert_not_called()
        mock_excepthook.assert_called_once_with(exc_type, exc_value, exc_traceback)
