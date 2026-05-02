import asyncio
import json
import logging
from pathlib import Path

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.errors import RequestsError

logger = logging.getLogger(__name__)

__all__ = ["SpecUpdater"]


class SpecUpdater:
    """
    Асинхронный менеджер обновлений (OTA Updates) для YAML спецификаций.
    Скачивает свежие правила парсинга перед запуском Диспетчера.
    """

    def __init__(self, specs_dir: Path, manifest_url: str) -> None:
        """
        Args:
            specs_dir: Директория, где лежат и куда будут скачиваться YAML файлы.
            manifest_url: URL к JSON-манифесту с версиями.
        """
        self.specs_dir = specs_dir
        self.manifest_url = manifest_url
        self.local_manifest_path: Path = self.specs_dir / "local_manifest.json"

    def _load_local_manifest(self) -> dict[str, str]:
        """Возвращает словарь {имя_файла: версия} из локального кэша."""
        if not self.local_manifest_path.exists():
            return {}
        try:
            with open(self.local_manifest_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception as e:
            logger.warning(f"Ошибка чтения локального манифеста: {e}")
            return {}

    def _save_local_manifest(self, manifest: dict[str, str]) -> None:
        """Сохраняет обновленные версии в локальный кэш."""
        try:
            self.specs_dir.mkdir(parents=True, exist_ok=True)
            with open(self.local_manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except Exception as e:
            logger.error(f"Не удалось сохранить локальный манифест: {e}")

    async def _download_file(self, client: AsyncSession, url: str, target_path: Path) -> bool:
        """Скачивает один YAML файл и сохраняет на диск."""
        try:
            response = await client.get(url, timeout=15.0)
            response.raise_for_status()

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            return True
        except Exception as e:
            logger.error(f"Ошибка загрузки {target_path.name} из {url}: {e}")
            return False

    async def update_specs(self) -> list[str]:
        """
        Проверяет и скачивает обновления спецификаций.
        Возвращает список обновленных файлов (для уведомления пользователя в UI).
        """
        logger.info("Поиск обновлений для правил парсинга (Specs)...")
        updated_files: list[str] = []

        if not self.manifest_url:
            logger.warning("URL манифеста не задан, обновление пропущено.")
            return []

        try:
            async with AsyncSession(timeout=10.0, impersonate="chrome120") as client:
                # 1. Загружаем удаленный манифест
                try:
                    resp = await client.get(self.manifest_url)
                    resp.raise_for_status()
                    remote_manifest = resp.json()

                    if not isinstance(remote_manifest, dict):
                        raise ValueError("Манифест должен быть JSON-словарем")

                except RequestsError as e:
                    logger.warning(
                        f"Нет связи с сервером обновлений ({e}). Используем локальные правила."
                    )
                    return []
                except Exception as e:
                    logger.warning(f"Сбой загрузки манифеста: {e}. Используем локальные правила.")
                    return []

                # 2. Сравниваем с локальными версиями
                local_versions = self._load_local_manifest()
                tasks = []
                files_to_update = []

                for filename, meta in remote_manifest.items():
                    if not isinstance(meta, dict):
                        continue

                    remote_version = meta.get("version")
                    download_url = meta.get("url")

                    if not remote_version or not download_url:
                        continue

                    local_version = local_versions.get(filename)
                    target_path = self.specs_dir / filename

                    # Обновляем, если версия изменилась ИЛИ файла физически нет на диске
                    if remote_version != local_version or not target_path.exists():
                        logger.info(
                            f"Найдено обновление для {filename}: {local_version} -> {remote_version}"
                        )
                        files_to_update.append((filename, remote_version))
                        # Создаем асинхронную задачу на скачивание
                        tasks.append(self._download_file(client, download_url, target_path))

                # 3. Скачиваем все измененные файлы параллельно
                if tasks:
                    results = await asyncio.gather(*tasks)

                    # 4. Обновляем локальный манифест только для УСПЕШНО скачанных файлов
                    for (filename, new_version), success in zip(files_to_update, results, strict=True):
                        if success:
                            local_versions[filename] = new_version
                            updated_files.append(filename)
                            logger.debug(f"Файл {filename} успешно обновлен до v{new_version}")

                    if updated_files:
                        self._save_local_manifest(local_versions)
                        logger.info(f"Успешно обновлено {len(updated_files)} спецификаций.")

        except Exception as e:
            logger.error(f"Непредвиденная ошибка при обновлении спецификаций: {e}", exc_info=True)

        return updated_files
