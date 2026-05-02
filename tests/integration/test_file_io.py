"""
Интеграционный тест подсистемы хранения данных (File I/O Pipeline).

Проверяет реальное взаимодействие классов:
SessionManager -> DataWriter -> Файловая система ОС -> Экспорт (openpyxl/csv).

Мы не мокаем ни один из этих классов. Всё происходит на реальном жестком диске (во временной папке).
"""

import csv
import json
from pathlib import Path

import openpyxl
import pytest

from core.file_manager import DataWriter, SessionManager


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Создает временную базовую директорию для интеграционного теста."""
    data_dir = tmp_path / "finist_data"
    data_dir.mkdir()
    return data_dir


def test_full_data_lifecycle(base_dir: Path):
    """
    Сквозной тест жизненного цикла данных.

    Важное архитектурное ограничение O(1)-экспортера:
    Заголовки Excel/CSV генерируются по ключам ПЕРВОЙ записи в JSONL.
    Поэтому первая запись должна содержать максимально полный набор полей.

    1. Создание сессии.
    2. Атомарная запись нескольких батчей данных (включая сложные типы).
    3. Успешный экспорт в CSV.
    4. Успешный экспорт в Excel (XLSX).
    5. Проверка корректности сохраненных данных в файлах.
    """
    # ШАГ 1: Инициализация сессии
    session_mgr = SessionManager(base_dir=base_dir)
    session_id = session_mgr.create_session()

    assert session_id.startswith("session_")
    assert (base_dir / session_id).exists()

    # ШАГ 2: Инициализация райтера и запись батчей
    writer = DataWriter(base_dir=base_dir, session_id=session_id, source="test_forum")

    # Батч 1: ПЕРВАЯ запись должна иметь ПОЛНЫЙ набор полей (это определит заголовки Excel/CSV).
    batch_1 = [
        {"id": 1, "author": "Alice", "text": "Hello world!", "tags": [], "meta": {}},
        {"id": 2, "author": "Bob", "text": "Integration tests rule.", "tags": [], "meta": {}},
    ]
    # Батч 2: Данные со сложными вложенными структурами (списки, словари) и пропущенными ключами
    batch_2 = [
        {
            "id": 3,
            "author": "Charlie",
            "text": "Deep data",
            "tags": ["test", "backend"],
            "meta": {"device": "pc"},
        },
        {"id": 4, "author": "", "text": "No author here", "tags": [], "meta": {}},
    ]

    writer.save_batch(batch_1)
    writer.save_batch(batch_2)

    # Проверяем, что JSONL создался и содержит 4 строки
    assert writer.jsonl_path.exists()
    lines = writer.jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 4

    # ШАГ 3: Экспорт в CSV
    csv_path = writer.export(fmt="csv")
    assert csv_path is not None
    assert csv_path.exists()

    # Проверяем содержимое CSV
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f, delimiter=";"))
        assert len(reader) == 4
        # Проверяем первую запись
        assert reader[0]["author"] == "Alice"
        assert reader[0]["text"] == "Hello world!"
        # Проверяем запись без автора (пустая строка, а не None)
        assert reader[3]["author"] == ""
        assert reader[3]["text"] == "No author here"

    # ШАГ 4: Экспорт в Excel
    xlsx_path = writer.export(fmt="xlsx")
    assert xlsx_path is not None
    assert xlsx_path.exists()

    # Проверяем содержимое Excel
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active

    # Извлекаем все строки в виде списка кортежей
    rows = list(ws.iter_rows(values_only=True))

    # 1 строка заголовков + 4 строки данных = 5 строк
    assert len(rows) == 5

    headers = rows[0]
    assert "id" in headers
    assert "author" in headers
    assert "text" in headers
    assert "tags" in headers
    assert "meta" in headers

    # Проверяем сериализацию сложных типов (Батч 2, id=3 -> индекс строки 3)
    row_charlie = rows[3]
    tags_idx = headers.index("tags")
    meta_idx = headers.index("meta")

    # Списки и словари должны быть сериализованы в JSON-строки
    assert row_charlie[tags_idx] == '["test", "backend"]'
    assert row_charlie[meta_idx] == '{"device": "pc"}'


def test_session_manager_lists_sessions(base_dir: Path):
    """
    Проверяет, что SessionManager корректно находит и сортирует сессии на диске.
    """
    mgr = SessionManager(base_dir=base_dir)

    # Создаем несколько сессий с паузами (чтобы имена папок были уникальными)
    session_ids = [mgr.create_session() for _ in range(3)]

    # Список должен возвращаться от новой к старой
    listed = mgr.list_sessions()
    assert len(listed) == 3
    assert listed == sorted(session_ids, reverse=True)


def test_data_writer_no_data_returns_none(base_dir: Path):
    """
    Если JSONL файла нет, экспорт возвращает None без ошибок.
    """
    writer = DataWriter(base_dir=base_dir, session_id="empty_session", source="ghost")

    result_csv = writer.export("csv")
    result_xlsx = writer.export("xlsx")

    assert result_csv is None
    assert result_xlsx is None


def test_data_writer_concurrent_batches(base_dir: Path):
    """
    Проверяет, что несколько последовательных батчей корректно дописываются
    в один JSONL файл (append-логика, а не перезапись).
    """
    writer = DataWriter(base_dir=base_dir, session_id="concurrent", source="test")

    for i in range(5):
        writer.save_batch([{"index": i, "data": f"batch_{i}"}])

    lines = writer.jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5

    for i, line in enumerate(lines):
        record = json.loads(line)
        assert record["index"] == i
        assert record["data"] == f"batch_{i}"
