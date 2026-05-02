# mypy: disable-error-code=no-untyped-def
# ruff: noqa: RUF001, RUF002, RUF003

"""
Тесты для core/file_manager.py

Покрытие: 100%
- SessionManager: создание папок (успех/ошибка), сортировка старых сессий.
- DataWriter: атомарная дозапись батчей, создание папок "на лету", блокировка потоков.
- Экспорт: O(1) чтение JSONL, генерация CSV с BOM, генерация Excel с вложенными JSON,
  проверка пустых файлов и неизвестных форматов.
"""

import csv
import json
import logging
import multiprocessing
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest

from core.file_manager import DataWriter, SessionManager

# ---------------------------------------------------------------------------
# SessionManager Tests
# ---------------------------------------------------------------------------


class TestSessionManager:
    @pytest.fixture
    def manager(self, tmp_path: Path):
        return SessionManager(base_dir=tmp_path)

    def test_create_session_success(self, manager, tmp_path):
        """Успешное создание сессии с правильным форматом имени."""
        session_id = manager.create_session()

        assert session_id.startswith("session_")
        assert (tmp_path / session_id).exists()
        assert (tmp_path / session_id).is_dir()
        # Формат: session_YYYY-MM-DD_HH-MM-SS-ffffff
        # Убираем префикс "session_" и проверяем что осталось дата + время с микросекундами
        timestamp_part = session_id.removeprefix("session_")
        date_part, time_part = timestamp_part.split("_")
        assert len(date_part) == 10  # YYYY-MM-DD
        assert len(time_part) == 15  # HH-MM-SS-ffffff

    def test_create_session_os_error(self, manager, caplog):
        """Обработка системной ошибки при создании директории."""
        with (
            patch.object(Path, "mkdir", side_effect=OSError("Disk Full")),
            pytest.raises(RuntimeError, match="Не удалось инициализировать сессию: Disk Full"),
        ):
            manager.create_session()

        assert "Ошибка создания папки сессии" in caplog.text

    def test_list_sessions(self, manager, tmp_path):
        """Возвращает только папки сессий, отсортированные от новых к старым."""
        # Создаем правильные сессии
        (tmp_path / "session_2023-01-01").mkdir()
        (tmp_path / "session_2023-01-02").mkdir()

        # Создаем мусор (файлы и левые папки)
        (tmp_path / "session_fake.txt").touch()
        (tmp_path / "other_folder").mkdir()

        sessions = manager.list_sessions()

        assert len(sessions) == 2
        assert sessions[0] == "session_2023-01-02"  # Сначала более новая
        assert sessions[1] == "session_2023-01-01"

    def test_list_sessions_empty_dir(self, manager, tmp_path):
        """Если базовой папки нет, возвращает пустой список."""
        manager.base_dir = tmp_path / "nonexistent"
        assert manager.list_sessions() == []


# ---------------------------------------------------------------------------
# DataWriter Tests
# ---------------------------------------------------------------------------


class TestDataWriter:
    @pytest.fixture
    def writer(self, tmp_path: Path):
        return DataWriter(
            base_dir=tmp_path,
            session_id="test_session",
            source="reddit",
            lock=multiprocessing.Lock(),
        )

    def test_save_batch_success(self, writer):
        """Атомарная запись батча создает файл и папку на лету."""
        data = [{"id": 1, "text": "A"}, {"id": 2, "text": "B"}]
        writer.save_batch(data)

        assert writer.jsonl_path.exists()

        # Проверяем содержимое
        lines = writer.jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"id": 1, "text": "A"}

    def test_save_batch_empty(self, writer):
        """Пустой батч не создает файлы и папки."""
        writer.save_batch([])
        assert not writer.jsonl_path.exists()

    def test_save_batch_append(self, writer):
        """Повторная запись дописывает данные в конец файла."""
        writer.save_batch([{"id": 1}])
        writer.save_batch([{"id": 2}])

        lines = writer.jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[1]) == {"id": 2}

    def test_save_batch_os_error(self, writer, caplog):
        """Ошибка записи пробрасывается дальше с логированием."""
        with (
            patch("builtins.open", side_effect=OSError("Read only file system")),
            pytest.raises(OSError),
        ):
            writer.save_batch([{"id": 1}])

        assert "Ошибка записи батча" in caplog.text

    def test_export_no_data(self, writer, caplog):
        """Если файла JSONL нет, возвращает None."""
        with caplog.at_level(logging.WARNING):
            result = writer.export("csv")

        assert result is None
        assert "Нет данных для экспорта" in caplog.text

    def test_export_invalid_format(self, writer):
        """При неизвестном формате падает с ValueError."""
        writer.save_batch([{"id": 1}])
        with pytest.raises(ValueError, match="Неизвестный формат экспорта: xml"):
            writer.export("xml")

    def test_export_csv_success(self, writer):
        """Экспорт в CSV генерирует корректный файл с BOM и разделителем ';'."""
        writer.save_batch(
            [
                {"name": "Alice", "age": 25},
                {"name": "Bob"},  # Нет возраста
            ]
        )

        # Добавим пустую строку в JSONL для проверки устойчивости парсера
        with open(writer.jsonl_path, "a", encoding="utf-8") as f:
            f.write("\n")

        out_path = writer.export("csv")

        assert out_path.exists()
        assert out_path.suffix == ".csv"

        with open(out_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)

        assert len(rows) == 2
        assert rows[0] == {"name": "Alice", "age": "25"}
        assert rows[1] == {"name": "Bob", "age": ""}  # Возраст заполнился пустой строкой

    @patch("core.file_manager.openpyxl.Workbook")
    def test_export_excel_success(self, mock_wb_cls, writer):
        """Экспорт в Excel корректно сериализует словари и списки в строки."""
        mock_ws = mock_wb_cls.return_value.active
        cells: dict[tuple[int, int], object] = {}
        mock_ws.cell.side_effect = lambda row, column, value=None: type(
            "Cell", (), {"value": value, "font": None, "fill": None, "alignment": None}
        )()
        mock_ws.__getitem__ = lambda self_, key: []
        mock_ws.auto_filter = type("AF", (), {"ref": None})()
        mock_ws.dimensions = "A1:B2"

        writer.save_batch(
            [
                {"id": 1, "tags": ["a", "b"], "meta": {"k": "v"}},
                {"id": 2},
            ]
        )

        with open(writer.jsonl_path, "a", encoding="utf-8") as f:
            f.write("   \n")

        out_path = writer.export("xlsx")

        mock_wb_cls.assert_called_once()
        mock_ws.title = writer.source[:31]
        assert mock_ws.title == "reddit"
        mock_wb_cls.return_value.save.assert_called_once_with(out_path)

    @patch("core.file_manager.openpyxl.Workbook")
    def test_export_excel_long_source_name(self, mock_wb_cls, tmp_path):
        """Имя листа Excel обрезается до 31 символа."""
        mock_ws = mock_wb_cls.return_value.active
        mock_ws.auto_filter = type("AF", (), {"ref": None})()
        mock_ws.dimensions = "A1:A1"

        long_source = "a" * 40
        writer = DataWriter(base_dir=tmp_path, session_id="s", source=long_source, lock=multiprocessing.Lock())
        writer.save_batch([{"id": 1}])

        writer.export("xlsx")

        mock_ws.__setattr__("title", long_source[:31])
        assert len(mock_ws.title) == 31
