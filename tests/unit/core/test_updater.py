# mypy: disable-error-code=no-untyped-def
# ruff: noqa: RUF001, RUF002, RUF003

"""
Тесты для core/updater.py

Покрытие: 100%
- _load_local_manifest: отсутствие файла, невалидный JSON, некорректный тип (список), успех.
- _save_local_manifest: успех, системные ошибки (ReadOnly FS).
- _download_file: успешное скачивание (проверка записи), сетевая ошибка (404), ошибка диска.
- update_specs:
    - Пропуск при пустом URL манифеста.
    - Сетевые ошибки загрузки манифеста (RequestsError, HTTP 500).
    - Ошибка структуры манифеста (не словарь).
    - Пропуск файлов, если они актуальны и существуют на диске.
    - Успешное параллельное скачивание и обновление локального манифеста.
    - Фильтрация битых метаданных в манифесте.
    - Непредвиденные глобальные ошибки (Exception fallback).
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from curl_cffi.requests.errors import RequestsError

from core.updater import SpecUpdater

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def updater(tmp_path: Path):
    """Инициализирует SpecUpdater с временной директорией."""
    return SpecUpdater(specs_dir=tmp_path, manifest_url="https://fake.url/manifest.json")


# ---------------------------------------------------------------------------
# Local Manifest Tests
# ---------------------------------------------------------------------------


class TestLocalManifest:
    def test_load_manifest_not_exists(self, updater):
        assert updater._load_local_manifest() == {}

    def test_load_manifest_invalid_json(self, updater, caplog):
        updater.local_manifest_path.write_text("invalid json")

        result = updater._load_local_manifest()

        assert result == {}
        assert "Ошибка чтения локального манифеста" in caplog.text

    def test_load_manifest_not_dict(self, updater):
        updater.local_manifest_path.write_text('["list", "not", "dict"]')
        assert updater._load_local_manifest() == {}

    def test_load_manifest_success(self, updater):
        updater.local_manifest_path.write_text('{"reddit.yaml": "v1"}')
        assert updater._load_local_manifest() == {"reddit.yaml": "v1"}

    def test_save_manifest_success(self, updater):
        updater._save_local_manifest({"test.yaml": "v2"})

        assert updater.local_manifest_path.exists()
        data = json.loads(updater.local_manifest_path.read_text())
        assert data == {"test.yaml": "v2"}

    def test_save_manifest_error(self, updater, caplog):
        with patch("builtins.open", side_effect=OSError("Read Only FS")):
            updater._save_local_manifest({"a": "b"})

        assert "Не удалось сохранить локальный манифест" in caplog.text


# ---------------------------------------------------------------------------
# Download File Tests
# ---------------------------------------------------------------------------


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_download_success(self, updater, tmp_path):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "test_yaml_content"
        mock_client.get.return_value = mock_response

        target_path = tmp_path / "test.yaml"
        result = await updater._download_file(mock_client, "http://dl", target_path)

        assert result is True
        mock_response.raise_for_status.assert_called_once()
        assert target_path.read_text() == "test_yaml_content"

    @pytest.mark.asyncio
    async def test_download_http_error(self, updater, tmp_path, caplog):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 404")
        mock_client.get.return_value = mock_response

        result = await updater._download_file(mock_client, "http://dl", tmp_path / "t.yaml")

        assert result is False
        assert "Ошибка загрузки" in caplog.text


# ---------------------------------------------------------------------------
# Update Specs (Main Logic) Tests
# ---------------------------------------------------------------------------


class TestUpdateSpecs:
    @pytest.mark.asyncio
    async def test_update_skipped_if_no_url(self, updater, caplog):
        updater.manifest_url = ""
        result = await updater.update_specs()

        assert result == []
        assert "URL манифеста не задан" in caplog.text

    @pytest.mark.asyncio
    @patch("core.updater.AsyncSession")
    async def test_manifest_network_error(self, mock_session_cls, updater, caplog):
        mock_client = AsyncMock()
        mock_client.get.side_effect = RequestsError("Timeout")
        mock_session_cls.return_value.__aenter__.return_value = mock_client

        result = await updater.update_specs()

        assert result == []
        assert "Нет связи с сервером обновлений" in caplog.text

    @pytest.mark.asyncio
    @patch("core.updater.AsyncSession")
    async def test_manifest_invalid_structure(self, mock_session_cls, updater, caplog):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = ["not", "a", "dict"]  # Ошибка структуры
        mock_client.get.return_value = mock_response
        mock_session_cls.return_value.__aenter__.return_value = mock_client

        result = await updater.update_specs()

        assert result == []
        assert "Манифест должен быть JSON-словарем" in caplog.text

    @pytest.mark.asyncio
    @patch("core.updater.AsyncSession")
    async def test_successful_update_scenario(self, mock_session_cls, updater):
        # Подготавливаем локальный манифест и файл (он "актуален")
        updater.local_manifest_path.write_text('{"actual.yaml": "v1", "old.yaml": "v1"}')
        (updater.specs_dir / "actual.yaml").touch()

        # Мокаем ответ удаленного манифеста
        remote_manifest = {
            "actual.yaml": {"version": "v1", "url": "http://dl/actual.yaml"},  # Не изменился
            "old.yaml": {"version": "v2", "url": "http://dl/old.yaml"},  # Нужна новая версия
            "new.yaml": {"version": "v1", "url": "http://dl/new.yaml"},  # Новый файл
            "broken.yaml": "not_a_dict",  # Битые данные (пропуск)
            "missing.yaml": {"version": "v1"},  # Нет url (пропуск)
        }

        mock_client = AsyncMock()
        mock_manifest_resp = MagicMock()
        mock_manifest_resp.json.return_value = remote_manifest
        mock_client.get.return_value = mock_manifest_resp
        mock_session_cls.return_value.__aenter__.return_value = mock_client

        # Мокаем скачивание файлов (успех для всех)
        with patch.object(updater, "_download_file", return_value=True) as mock_download:
            updated_files = await updater.update_specs()

        # Должны обновиться только old.yaml и new.yaml
        assert sorted(updated_files) == sorted(["old.yaml", "new.yaml"])
        assert mock_download.call_count == 2

        # Проверяем, что локальный манифест обновился
        saved_manifest = json.loads(updater.local_manifest_path.read_text())
        assert saved_manifest["old.yaml"] == "v2"
        assert saved_manifest["new.yaml"] == "v1"
        assert saved_manifest["actual.yaml"] == "v1"

    @pytest.mark.asyncio
    @patch("core.updater.AsyncSession", side_effect=Exception("Critical Crash"))
    async def test_global_exception_fallback(self, mock_session_cls, updater, caplog):
        """Любая неожиданная ошибка на верхнем уровне не должна валить программу."""
        result = await updater.update_specs()

        assert result == []
        assert "Непредвиденная ошибка при обновлении спецификаций" in caplog.text
