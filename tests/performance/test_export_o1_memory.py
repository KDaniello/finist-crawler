"""
Performance тест: Экспорт данных с O(1) по памяти.
Доказывает, что экспорт 100 000 записей не вызывает всплеска ОЗУ.
"""

import json
import os
from pathlib import Path

import psutil

from core.file_manager import DataWriter


def test_csv_export_memory_efficiency(tmp_path: Path):
    """
    СЦЕНАРИЙ: Генерируем JSONL файл на 100 000 строк (~10 МБ на диске). Экспортируем в CSV.
    ОЖИДАНИЕ: Оперативная память во время экспорта вырастет не более чем на 5 МБ,
              так как экспорт читает файл построчно O(1).
    """
    session_id = "perf_session"
    source = "massive_data"

    writer = DataWriter(base_dir=tmp_path, session_id=session_id, source=source)
    writer.source_dir.mkdir(parents=True, exist_ok=True)

    # 1. Генерируем массивный JSONL напрямую (чтобы не нагружать память списками Python)
    # 100 000 строк - это серьезный объем для десктопного парсера
    with open(writer.jsonl_path, "w", encoding="utf-8") as f:
        for i in range(100_000):
            record = {
                "id": i,
                "author": f"User_{i}",
                "text": "Это очень длинный текст " * 10,
                "metadata": {"tags": ["perf", "test"]},
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    assert writer.jsonl_path.exists()
    file_size_mb = writer.jsonl_path.stat().st_size / (1024 * 1024)
    assert file_size_mb > 5.0  # Убеждаемся, что файл реально весомый

    process = psutil.Process(os.getpid())

    # ЗАМЕР: Память ДО экспорта
    mem_before_mb = process.memory_info().rss / (1024 * 1024)

    # 2. Выполняем потоковый экспорт в CSV
    csv_path = writer.export(fmt="csv")

    # ЗАМЕР: Память ПОСЛЕ экспорта
    mem_after_mb = process.memory_info().rss / (1024 * 1024)
    growth_mb = mem_after_mb - mem_before_mb

    assert csv_path is not None
    assert csv_path.exists()

    # Проверка O(1): Чтение 10 МБ файла должно добавить в ОЗУ от силы пару мегабайт на буферы
    assert growth_mb < 5.0, f"Всплеск памяти при экспорте CSV: {growth_mb:.2f} MB. Экспорт не O(1)!"
