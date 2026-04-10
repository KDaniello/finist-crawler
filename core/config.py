import logging
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ProjectPaths", "Settings", "get_paths", "get_settings", "setup_environment"]

logger = logging.getLogger(__name__)


class ProjectPaths:
    """
    Разрешение путей с учётом PyInstaller.

    Все свойства — чистые вычисления без I/O, кроме `specs_dir`,
    который явно помечен как выполняющий проверку файловой системы.
    """

    @property
    def root_dir(self) -> Path:
        """Директория рядом с .exe или корень проекта в dev-режиме."""
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path(__file__).resolve().parent.parent

    @property
    def internal_dir(self) -> Path:
        """
        Временная директория PyInstaller (_MEIPASS).
        В dev-режиме совпадает с root_dir.

        Raises:
            RuntimeError: Если приложение собрано, но _MEIPASS отсутствует.
                          Это признак повреждённой сборки PyInstaller.
        """
        if getattr(sys, "frozen", False):
            meipath = getattr(sys, "_MEIPASS", None)
            if meipath is None:
                # print-fallback: логгер ещё не инициализирован на этом этапе
                print(
                    "[CRITICAL] sys._MEIPASS не найден в собранном приложении.",
                    file=sys.stderr,
                )
                raise RuntimeError(
                    "Критическая ошибка: sys._MEIPASS не найден в собранном приложении."
                )
            return Path(meipath)
        return self.root_dir

    @property
    def env_file(self) -> Path:
        return self.root_dir / ".env"

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def logs_dir(self) -> Path:
        return self.root_dir / "logs"

    @property
    def proxies_file(self) -> Path:
        return self.root_dir / "proxies.txt"

    @property
    def specs_dir(self) -> Path:
        """
        Возвращает директорию со спецификациями парсеров.

        Приоритет: внешняя папка (кастомные спеки пользователя) → внутренняя (бандл).

        Note:
            Выполняет Path.exists() — I/O операция.
            Не вызывайте в hot-path (используйте результат один раз и кэшируйте).
        """
        external = self.root_dir / "specs"
        if external.exists():
            return external
        return self.internal_dir / "specs"


def _make_settings(env_file: Path) -> "Settings":
    """
    Фабрика Settings с динамическим путём к .env.

    Выделена отдельно, чтобы lru_cache на get_settings() не захватывал
    изменяемый аргумент, а путь определялся один раз через get_paths().
    """
    # pydantic-settings v2: _env_file передаётся как keyword-аргумент модели,
    # переопределяя значение из model_config только для этого экземпляра.
    return Settings(_env_file=env_file)  # type: ignore[call-arg]


class Settings(BaseSettings):
    """
    Конфигурация приложения (иммутабельной DTO).

    Никаких сайд-эффектов и File I/O внутри класса.
    Значения берутся из .env → переменных окружения → defaults.
    """

    APP_NAME: str = "Finist Crawler"
    VERSION: str = "0.1.0 Alpha"
    DEBUG: bool = Field(default=False, validation_alias="DEBUG_MODE")

    # Системные лимиты (важно для слабых ПК)
    MAX_RECORDS_IN_MEMORY: int = Field(
        default=10_000,
        description="Сброс буфера на диск каждые N записей",
        gt=0,
    )

    # Discord интеграция
    DISCORD_WEBHOOK_URL: str | None = None

    # Прокси по умолчанию (если нет файла proxies.txt)
    PROXY_URL: str | None = None

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_paths() -> ProjectPaths:
    """
    Возвращает singleton ProjectPaths.

    lru_cache гарантирует, что объект создаётся один раз за время жизни процесса.
    """
    return ProjectPaths()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Возвращает singleton Settings.

    Путь к .env определяется через get_paths(), что корректно работает
    как в dev-режиме, так и внутри PyInstaller-сборки.
    """
    paths = get_paths()
    return _make_settings(paths.env_file)


def setup_environment() -> None:
    """
    Создаёт базовые директории и файлы для работы приложения.

    Должна вызываться строго один раз в точке входа (main.py),
    до старта мультипроцессинга и инициализации логгера.

    Raises:
        RuntimeError: Если не удалось создать директорию или файл.
        Содержит путь и системную ошибку.
    """
    paths = get_paths()

    directories: list[Path] = [
        paths.data_dir,
        paths.profiles_dir,
        paths.logs_dir,
    ]

    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug("Директория готова: %s", directory)
        except OSError as e:
            # logger может быть не настроен — дублируем в stderr
            print(f"[ERROR] Не удалось создать директорию {directory}: {e}", file=sys.stderr)
            raise RuntimeError(f"Не удалось создать директорию {directory}: {e}") from e

    if not paths.proxies_file.exists():
        try:
            paths.proxies_file.touch()
            logger.debug("Создан пустой файл прокси: %s", paths.proxies_file)
        except OSError as e:
            print(f"[ERROR] Не удалось создать {paths.proxies_file}: {e}", file=sys.stderr)
            raise RuntimeError(f"Не удалось создать {paths.proxies_file}: {e}") from e

    logger.info("Окружение инициализировано. Root: %s", paths.root_dir)
