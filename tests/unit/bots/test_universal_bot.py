"""
Тесты для bots/universal_bot.py

Покрытие: 100%
- Инициализация логирования и синглтонов.
- Успешный запуск бота: правильная передача зависимостей в классы.
- Работа замыкания (callback) save_records: сохранение батча, игнорирование пустого списка.
- Обработка source_key по умолчанию (отрезание .yaml от имени файла).
- Перехват asyncio.CancelledError (штатная остановка).
- Перехват глобального Exception (критический сбой).
- Перехват KeyboardInterrupt на уровне asyncio.run (штатное прерывание из консоли).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bots.universal_bot import run_universal_bot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_deps():
    """Мокает все внешние зависимости (Core и Engine) для чистой изоляции слоя Bots."""
    with (
        patch("bots.universal_bot.setup_worker_logging") as m_log,
        patch("bots.universal_bot.get_settings") as m_settings,
        patch("bots.universal_bot.get_paths") as m_paths,
        patch("bots.universal_bot.load_spec") as m_load,
        patch("bots.universal_bot.build_plan") as m_build,
        patch("bots.universal_bot.DataWriter") as m_writer,
        patch("bots.universal_bot.FallbackOrchestrator") as m_orch,
    ):
        # Настраиваем фейковые пути и настройки
        m_settings.return_value.PROXY_URL = "http://proxy"
        m_paths.return_value.specs_dir = "/fake/specs"
        m_paths.return_value.data_dir = "/fake/data"
        m_paths.return_value.profiles_dir = Path("/fake/profiles")

        # Настраиваем фейковую спецификацию
        m_load.return_value = {"source_key": "custom_domain"}

        # Настраиваем фейковый план
        m_plan = MagicMock()
        m_plan.render_strategy = "auto"
        m_plan.start_urls = ["http://test"]
        m_build.return_value = m_plan

        # Настраиваем фейковый DataWriter
        m_writer_inst = MagicMock()
        m_writer.return_value = m_writer_inst

        # Настраиваем фейковый Orchestrator
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUniversalBot:
    def test_run_success_and_callback(self, mock_deps, caplog):
        """Успешный прогон: проверка инъекции зависимостей и работы коллбека save_records."""
        log_queue = MagicMock()
        browser_lock = MagicMock()

        # Запускаем бота
        run_universal_bot("test.yaml", "sess_123", {"max_pages": 5}, log_queue, browser_lock)

        # 1. Проверяем настройку логгера
        mock_deps["log"].assert_called_once_with(log_queue)

        # 2. Проверяем загрузку спеки с правильными путями
        mock_deps["load"].assert_called_once_with("test.yaml", "/fake/specs")
        mock_deps["build"].assert_called_once_with(
            {"source_key": "custom_domain"}, {"max_pages": 5}
        )

        # 3. Проверяем создание писателя
        mock_deps["writer"].assert_called_once_with(
            base_dir="/fake/data", session_id="sess_123", source="custom_domain"
        )

        # 4. Проверяем передачу прокси и создание оркестратора
        mock_deps["orch"].assert_called_once_with(
            browser_lock=browser_lock, profiles_dir=Path("/fake/profiles"), render_strategy="auto"
        )
        mock_deps["orch_inst"].execute_plan.assert_called_once()

        # 5. Тестируем само замыкание (callback) `save_records`
        kwargs = mock_deps["orch_inst"].execute_plan.call_args.kwargs
        assert kwargs["plan"] == mock_deps["plan"]
        assert kwargs["proxy_url"] == "http://proxy"

        save_cb = kwargs["save_cb"]

        # Пустой список игнорируется
        save_cb([])
        mock_deps["writer_inst"].save_batch.assert_not_called()

        # Список с данными сохраняется
        save_cb([{"id": 1}])
        mock_deps["writer_inst"].save_batch.assert_called_once_with([{"id": 1}])

        # Проверяем успешный лог
        assert "успешно завершен" in caplog.text

    def test_default_source_key(self, mock_deps):
        """Если source_key не указан в YAML, он генерируется из имени файла."""
        mock_deps["load"].return_value = {}  # Нет ключа

        run_universal_bot("reddit.yaml", "sess_123", {}, MagicMock(), MagicMock())

        # Окончание .yaml должно отрезаться
        mock_deps["writer"].assert_called_once_with(
            base_dir="/fake/data", session_id="sess_123", source="reddit"
        )

    def test_run_cancelled_error(self, mock_deps, caplog):
        """Остановка через Dispatcher.stop_all() логируется как WARNING."""
        mock_deps["orch_inst"].execute_plan.side_effect = asyncio.CancelledError()

        run_universal_bot("test.yaml", "sess_123", {}, MagicMock(), MagicMock())

        assert "принудительно остановлен пользователем" in caplog.text
        assert "завершает работу" in caplog.text

    def test_run_general_exception(self, mock_deps, caplog):
        """Глобальная ошибка логируется как CRITICAL."""
        mock_deps["build"].side_effect = ValueError("Broken YAML structure")

        run_universal_bot("test.yaml", "sess_123", {}, MagicMock(), MagicMock())

        assert "Критическая ошибка в боте" in caplog.text
        assert "Broken YAML structure" in caplog.text
        assert "завершает работу" in caplog.text

    @patch("asyncio.run")
    def test_run_keyboard_interrupt(self, mock_asyncio_run, mock_deps):
        """Ctrl+C (KeyboardInterrupt) игнорируется воркером, так как его ловит главный процесс."""
        mock_asyncio_run.side_effect = KeyboardInterrupt()

        # Не должно упасть
        run_universal_bot("test.yaml", "sess_123", {}, MagicMock(), MagicMock())
        mock_asyncio_run.assert_called_once()
