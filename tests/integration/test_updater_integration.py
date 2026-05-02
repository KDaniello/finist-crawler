"""
Интеграционный тест системы OTA обновлений (Over-The-Air).
Связка: SpecUpdater + AsyncSession (curl_cffi) + Локальная файловая система.
"""

import json
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from core.updater import SpecUpdater


@pytest.mark.asyncio
async def test_spec_updater_full_cycle(httpserver: HTTPServer, tmp_path: Path):
    """
    СЦЕНАРИЙ:
    1. Сервер отдает манифест с v1.0. Файл скачивается.
    2. Повторный запуск с тем же манифестом -> ничего не скачивается (кэш).
    3. Сервер обновляет манифест до v2.0 -> файл скачивается заново.
    """
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()

    # --- ЭТАП 1: Первый запуск (v1.0) ---

    manifest_v1 = {
        "test_forum.yaml": {"version": "1.0", "url": httpserver.url_for("/test_forum.yaml")}
    }

    httpserver.expect_oneshot_request("/manifest.json").respond_with_json(manifest_v1)
    httpserver.expect_oneshot_request("/test_forum.yaml").respond_with_data(
        "version: 1.0\nflow: [list]"
    )

    updater = SpecUpdater(specs_dir=specs_dir, manifest_url=httpserver.url_for("/manifest.json"))

    updated_files = await updater.update_specs()

    assert updated_files == ["test_forum.yaml"]
    assert (specs_dir / "test_forum.yaml").exists()
    assert "version: 1.0" in (specs_dir / "test_forum.yaml").read_text()

    # Проверяем, что локальный манифест сохранился
    local_manifest = json.loads((specs_dir / "local_manifest.json").read_text())
    assert local_manifest["test_forum.yaml"] == "1.0"

    # --- ЭТАП 2: Повторный запуск (нет изменений) ---

    httpserver.expect_oneshot_request("/manifest.json").respond_with_json(manifest_v1)

    # Внимание: мы НЕ настраиваем ответ для /test_forum.yaml, так как запрос не должен отправляться!
    updated_files_2 = await updater.update_specs()

    assert updated_files_2 == []  # Список обновленных файлов пуст

    # --- ЭТАП 3: Выход новой версии (v2.0) ---

    manifest_v2 = {
        "test_forum.yaml": {"version": "2.0", "url": httpserver.url_for("/test_forum_v2.yaml")}
    }

    httpserver.expect_oneshot_request("/manifest.json").respond_with_json(manifest_v2)
    httpserver.expect_oneshot_request("/test_forum_v2.yaml").respond_with_data(
        "version: 2.0\nflow: [list]"
    )

    updated_files_3 = await updater.update_specs()

    assert updated_files_3 == ["test_forum.yaml"]
    assert "version: 2.0" in (specs_dir / "test_forum.yaml").read_text()
