# mypy: disable-error-code=no-untyped-def
# ruff: noqa: RUF001, RUF002, RUF003

"""
Тесты для core/dispatcher.py

Покрытие: 100%
- Проверка инициализации с правильным контекстом ('spawn')
- Запуск процессов: успех, пустое демо, блокировка повторного запуска, перехват исключений
- Остановка: graceful shutdown (terminate -> join), hard kill (kill), пропуск уже мертвых
- is_running: очистка завершенных процессов, правильное логирование кодов возврата
"""

import logging
import multiprocessing
from unittest.mock import MagicMock, patch

import pytest

from core.dispatcher import Dispatcher

# ---------------------------------------------------------------------------
# Fixtures & Dummies
# ---------------------------------------------------------------------------


def dummy_worker(spec_name, session_id, config_overrides, log_queue, browser_lock):
    """Пустая функция для передачи в качестве WorkerCallable."""


@pytest.fixture
def mock_session_manager():
    """Мок, реализующий SessionManagerProtocol."""
    manager = MagicMock()
    manager.create_session.return_value = "session_mock_123"
    return manager


@pytest.fixture
def mock_log_queue():
    return MagicMock(spec=multiprocessing.Queue)


@pytest.fixture
def mock_ctx():
    """Перехватываем multiprocessing.get_context('spawn') до инициализации Dispatcher."""
    with patch("multiprocessing.get_context") as mock_get_context:
        ctx = MagicMock()
        mock_get_context.return_value = ctx
        yield ctx


@pytest.fixture
def dispatcher(mock_ctx, mock_session_manager, mock_log_queue):
    return Dispatcher(session_manager=mock_session_manager, log_queue=mock_log_queue)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDispatcherInit:
    def test_init_uses_spawn_context(self, mock_ctx, mock_session_manager, mock_log_queue):
        """Dispatcher должен запрашивать именно 'spawn' контекст для безопасности OС."""
        Dispatcher(session_manager=mock_session_manager, log_queue=mock_log_queue)

        # Проверяем импорт контекста
        import multiprocessing

        assert multiprocessing.get_context.call_args[0][0] == "spawn"  # type: ignore[attr-defined]

        # Проверяем, что lock создается через контекст
        mock_ctx.Lock.assert_called_once()

    def test_current_session_id_property(self, dispatcher):
        """Свойство current_session_id изначально None."""
        assert dispatcher.current_session_id is None


class TestDispatcherStartTasks:
    def test_start_tasks_empty_specs(self, dispatcher, caplog):
        """Если список спецификаций пуст, возвращает None и не вызывает процессы."""
        with caplog.at_level(logging.WARNING):
            result = dispatcher.start_tasks(dummy_worker, ["   ", ""], {})

        assert result is None
        assert "Нет спецификаций" in caplog.text

    def test_start_tasks_already_running(self, dispatcher, caplog):
        """Если процессы уже запущены, не дает запустить новые и возвращает старый session_id."""
        # Имитируем работающий процесс
        mock_proc = MagicMock()
        mock_proc.is_alive.return_value = True
        dispatcher._active_processes["test"] = mock_proc
        dispatcher._current_session_id = "old_session"

        with caplog.at_level(logging.WARNING):
            result = dispatcher.start_tasks(dummy_worker, ["new_spec"], {})

        assert result == "old_session"
        assert "предыдущие еще работают" in caplog.text

    def test_start_tasks_success(self, dispatcher, mock_ctx, mock_session_manager):
        """Успешный запуск создает процессы с правильными аргументами."""
        mock_proc = MagicMock()
        mock_proc.pid = 999
        mock_ctx.Process.return_value = mock_proc

        result = dispatcher.start_tasks(dummy_worker, ["reddit", "telegram"], {"fast": True})

        assert result == "session_mock_123"
        mock_session_manager.create_session.assert_called_once()

        # Проверяем, что Process вызван 2 раза (для reddit и telegram)
        assert mock_ctx.Process.call_count == 2

        # Проверяем аргументы первого вызова Process
        kwargs = mock_ctx.Process.call_args_list[0].kwargs
        assert kwargs["target"] == dummy_worker
        assert kwargs["name"] == "Worker-reddit"
        assert kwargs["daemon"] is True

        # Args: (spec_name, session_id, config_overrides, log_queue, browser_lock)
        args = kwargs["args"]
        assert args[0] == "reddit"
        assert args[1] == "session_mock_123"
        assert args[2] == {"fast": True}

        # Процессы должны быть запущены и добавлены в реестр
        assert mock_proc.start.call_count == 2
        assert "reddit" in dispatcher._active_processes
        assert "telegram" in dispatcher._active_processes

    def test_start_tasks_process_exception(self, dispatcher, mock_ctx, caplog):
        """Если при создании процесса возникла ошибка ОС, оркестратор не падает."""
        mock_ctx.Process.side_effect = OSError("Too many open files")

        with caplog.at_level(logging.ERROR):
            result = dispatcher.start_tasks(dummy_worker, ["bad_spec"], {})

        assert result == "session_mock_123"  # Сессия создалась
        assert len(dispatcher._active_processes) == 0  # Но процесс не добавлен
        assert "Не удалось запустить процесс" in caplog.text
        assert "Too many open files" in caplog.text


class TestDispatcherStopAll:
    def test_stop_all_empty(self, dispatcher, caplog):
        """Если нет активных процессов, метод завершается мгновенно."""
        with caplog.at_level(logging.INFO):
            dispatcher.stop_all()
        assert "Остановка всех процессов-воркеров" not in caplog.text

    def test_stop_all_graceful_success(self, dispatcher):
        """Нормальное завершение: процесс подчиняется SIGTERM."""
        proc = MagicMock()
        # Сначала процесс жив, после terminate -> мертв
        proc.is_alive.side_effect = [True, False, False]
        dispatcher._active_processes = {"spec1": proc}

        dispatcher.stop_all()

        proc.terminate.assert_called_once()
        proc.join.assert_called_once_with(timeout=3.0)
        proc.kill.assert_not_called()  # Жесткое убийство не понадобилось
        assert len(dispatcher._active_processes) == 0

    def test_stop_all_force_kill(self, dispatcher, caplog):
        """Если процесс игнорирует SIGTERM (повис), его убивают жестко SIGKILL."""
        proc = MagicMock()
        # Процесс всегда отвечает True (завис)
        proc.is_alive.return_value = True
        dispatcher._active_processes = {"spec1": proc}

        with caplog.at_level(logging.WARNING):
            dispatcher.stop_all()

        proc.terminate.assert_called_once()
        proc.join.assert_called_once_with(timeout=3.0)
        proc.kill.assert_called_once()
        assert "Принудительное убийство" in caplog.text
        assert len(dispatcher._active_processes) == 0

    def test_stop_all_already_dead_process(self, dispatcher):
        """Мертвым процессам не шлется SIGTERM, но вызывается join() для очистки ресурсов ОС."""
        proc = MagicMock()
        proc.is_alive.return_value = False
        dispatcher._active_processes = {"spec1": proc}

        dispatcher.stop_all()

        proc.terminate.assert_not_called()  # Нельзя терминировать то, что уже умерло
        proc.join.assert_called_once_with(timeout=3.0)  # Но ресурс освободить обязаны
        proc.kill.assert_not_called()


class TestDispatcherIsRunning:
    def test_is_running_all_alive(self, dispatcher):
        """Если все процессы живы, возвращает True и никого не удаляет."""
        proc = MagicMock()
        proc.is_alive.return_value = True
        dispatcher._active_processes = {"spec1": proc}

        assert dispatcher.is_running() is True
        assert len(dispatcher._active_processes) == 1

    def test_is_running_cleans_up_dead_processes(self, dispatcher, caplog):
        """Проверяет, что мертвые процессы удаляются из словаря, а их exitcode логируется."""
        proc_alive = MagicMock()
        proc_alive.is_alive.return_value = True

        proc_dead_success = MagicMock()
        proc_dead_success.is_alive.return_value = False
        proc_dead_success.exitcode = 0

        proc_dead_error = MagicMock()
        proc_dead_error.is_alive.return_value = False
        proc_dead_error.exitcode = 137  # SIGKILL например

        dispatcher._active_processes = {
            "alive": proc_alive,
            "success_dead": proc_dead_success,
            "error_dead": proc_dead_error,
        }

        with caplog.at_level(logging.INFO):
            result = dispatcher.is_running()

        assert result is True  # Т.к. есть один живой
        assert list(dispatcher._active_processes.keys()) == ["alive"]

        # Проверяем правильность логирования
        assert "успешно завершен" in caplog.text
        assert "завершился с кодом 137" in caplog.text

    def test_is_running_all_dead(self, dispatcher):
        """Если все процессы мертвы, возвращает False и очищает словарь полностью."""
        proc = MagicMock()
        proc.is_alive.return_value = False
        proc.exitcode = 0
        dispatcher._active_processes = {"spec1": proc}

        assert dispatcher.is_running() is False
        assert len(dispatcher._active_processes) == 0
