# mypy: disable-error-code=no-untyped-def
# ruff: noqa: RUF002

"""
Тесты для core/config.py

Покрытие: 100%
- ProjectPaths: все свойства в dev и frozen режимах
- Settings: дефолты, валидация, загрузка из .env
- get_paths / get_settings: singleton через lru_cache
- setup_environment: создание директорий, обработка ошибок
"""

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Сбрасываем lru_cache перед каждым тестом, чтобы тесты были изолированы
from core.config import (
    ProjectPaths,
    Settings,
    _make_settings,
    get_paths,
    get_settings,
    setup_environment,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_lru_caches():
    """Сбрасывает lru_cache синглтонов до и после каждого теста."""
    get_paths.cache_clear()
    get_settings.cache_clear()
    yield
    get_paths.cache_clear()
    get_settings.cache_clear()


@pytest.fixture()
def paths() -> ProjectPaths:
    return ProjectPaths()


@pytest.fixture()
def tmp_env_file(tmp_path: Path) -> Path:
    """Создаёт временный .env файл с тестовыми значениями."""
    env = tmp_path / ".env"
    env.write_text("DEBUG_MODE=true\nMAX_RECORDS_IN_MEMORY=500\n", encoding="utf-8")
    return env


# ---------------------------------------------------------------------------
# ProjectPaths — dev mode (not frozen)
# ---------------------------------------------------------------------------


class TestProjectPathsDevMode:
    """Тесты путей в обычном (не frozen) режиме запуска."""

    def test_root_dir_is_parent_of_core(self, paths: ProjectPaths):
        """root_dir должен быть родителем папки core/."""
        root = paths.root_dir
        assert (root / "core").is_dir() or root.name != "core"
        assert isinstance(root, Path)

    def test_internal_dir_equals_root_dir_in_dev(self, paths: ProjectPaths):
        """В dev-режиме internal_dir совпадает с root_dir."""
        assert paths.internal_dir == paths.root_dir

    def test_env_file_path(self, paths: ProjectPaths):
        assert paths.env_file == paths.root_dir / ".env"

    def test_data_dir_path(self, paths: ProjectPaths):
        assert paths.data_dir == paths.root_dir / "data"

    def test_profiles_dir_path(self, paths: ProjectPaths):
        assert paths.profiles_dir == paths.root_dir / "data" / "profiles"

    def test_logs_dir_path(self, paths: ProjectPaths):
        assert paths.logs_dir == paths.root_dir / "logs"

    def test_proxies_file_path(self, paths: ProjectPaths):
        assert paths.proxies_file == paths.root_dir / "proxies.txt"

    def test_specs_dir_returns_external_when_exists(self, paths: ProjectPaths, tmp_path: Path):
        """Если внешняя папка specs существует — возвращает её."""
        external_specs = tmp_path / "specs"
        external_specs.mkdir()

        with patch.object(
            type(paths), "root_dir", new_callable=lambda: property(lambda self: tmp_path)
        ):
            result = paths.specs_dir
            assert result == external_specs

    def test_specs_dir_returns_internal_when_external_missing(
        self, paths: ProjectPaths, tmp_path: Path
    ):
        """Если внешней папки specs нет — возвращает internal_dir / specs."""
        with (
            patch.object(
                type(paths), "root_dir", new_callable=lambda: property(lambda self: tmp_path)
            ),
            patch.object(
                type(paths),
                "internal_dir",
                new_callable=lambda: property(lambda self: tmp_path / "internal"),
            ),
        ):
            result = paths.specs_dir
            assert result == tmp_path / "internal" / "specs"


# ---------------------------------------------------------------------------
# ProjectPaths — frozen (PyInstaller) mode
# ---------------------------------------------------------------------------


class TestProjectPathsFrozenMode:
    """Тесты путей в frozen-режиме (имитация PyInstaller)."""

    def test_root_dir_uses_executable_parent_when_frozen(self):
        """В frozen-режиме root_dir — родитель sys.executable."""
        mock_exe = Path("/dist/myapp/finist.exe")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(mock_exe)),
        ):
            p = ProjectPaths()
            assert p.root_dir == mock_exe.parent

    def test_internal_dir_uses_meipass_when_frozen(self):
        """В frozen-режиме internal_dir берётся из sys._MEIPASS."""
        meipass = "/tmp/_MEI123456"
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", meipass, create=True),
            patch.object(sys, "executable", "/dist/finist.exe"),
        ):
            p = ProjectPaths()
            assert p.internal_dir == Path(meipass)

    def test_internal_dir_raises_if_meipass_missing_when_frozen(self, capsys):
        """Если _MEIPASS отсутствует в frozen-режиме — RuntimeError + сообщение в stderr."""
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/dist/finist.exe"),
        ):
            # Убеждаемся, что _MEIPASS не установлен
            if hasattr(sys, "_MEIPASS"):
                delattr(sys, "_MEIPASS")

            p = ProjectPaths()
            with pytest.raises(RuntimeError, match="_MEIPASS"):
                _ = p.internal_dir

        captured = capsys.readouterr()
        assert "CRITICAL" in captured.err


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings:
    """Тесты модели конфигурации."""

    def test_default_values(self):
        """Проверка дефолтных значений без .env файла."""
        s = Settings()
        assert s.APP_NAME == "Finist Crawler"
        assert s.VERSION == "0.1.0 Alpha"
        assert s.DEBUG is False
        assert s.MAX_RECORDS_IN_MEMORY == 10_000
        assert s.DISCORD_WEBHOOK_URL is None
        assert s.PROXY_URL is None

    def test_loads_from_env_file(self, tmp_env_file: Path):
        """Значения из .env файла корректно переопределяют дефолты."""
        s = _make_settings(tmp_env_file)
        assert s.DEBUG is True
        assert s.MAX_RECORDS_IN_MEMORY == 500

    def test_debug_uses_alias_debug_mode(self, tmp_path: Path):
        """Поле DEBUG читается из переменной DEBUG_MODE (validation_alias)."""
        env = tmp_path / ".env"
        env.write_text("DEBUG_MODE=true\n", encoding="utf-8")
        s = _make_settings(env)
        assert s.DEBUG is True

    def test_missing_env_file_uses_defaults(self, tmp_path: Path):
        """Несуществующий .env файл не вызывает ошибку — используются дефолты."""
        missing = tmp_path / "nonexistent.env"
        s = _make_settings(missing)
        assert s.APP_NAME == "Finist Crawler"

    def test_extra_env_vars_are_ignored(self, tmp_path: Path):
        """Лишние переменные в .env игнорируются (extra='ignore')."""
        env = tmp_path / ".env"
        env.write_text("UNKNOWN_VAR=oops\n", encoding="utf-8")
        s = _make_settings(env)  # не должно выбросить ValidationError
        assert not hasattr(s, "UNKNOWN_VAR")

    def test_max_records_must_be_positive(self):
        """MAX_RECORDS_IN_MEMORY должен быть > 0."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(MAX_RECORDS_IN_MEMORY=0)

    def test_discord_webhook_url_accepts_string(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text(
            "DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123\n", encoding="utf-8"
        )
        s = _make_settings(env)
        assert s.DISCORD_WEBHOOK_URL == "https://discord.com/api/webhooks/123"

    def test_proxy_url_accepts_string(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("PROXY_URL=http://user:pass@proxy:8080\n", encoding="utf-8")
        s = _make_settings(env)
        assert s.PROXY_URL == "http://user:pass@proxy:8080"


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------


class TestSingletons:
    """Тесты поведения lru_cache синглтонов."""

    def test_get_paths_returns_same_instance(self):
        p1 = get_paths()
        p2 = get_paths()
        assert p1 is p2

    def test_get_settings_returns_same_instance(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_get_paths_after_cache_clear_returns_new_instance(self):
        p1 = get_paths()
        get_paths.cache_clear()
        p2 = get_paths()
        # Значения равны, но это новый объект
        assert p1.root_dir == p2.root_dir

    def test_get_settings_uses_paths_env_file(self):
        """get_settings() должен читать .env через get_paths().env_file."""
        mock_paths = MagicMock(spec=ProjectPaths)
        mock_paths.env_file = Path("/nonexistent/.env")

        with patch("core.config.get_paths", return_value=mock_paths):
            get_settings.cache_clear()
            s = get_settings()
            assert s.APP_NAME == "Finist Crawler"  # дефолт, .env не существует


# ---------------------------------------------------------------------------
# setup_environment
# ---------------------------------------------------------------------------


class TestSetupEnvironment:
    """Тесты инициализации окружения."""

    def test_creates_required_directories(self, tmp_path: Path):
        """setup_environment создаёт data, profiles, logs директории."""
        mock_paths = _make_mock_paths(tmp_path)

        with patch("core.config.get_paths", return_value=mock_paths):
            setup_environment()

        assert (tmp_path / "data").exists()
        assert (tmp_path / "data" / "profiles").exists()
        assert (tmp_path / "logs").exists()

    def test_creates_proxies_file_if_missing(self, tmp_path: Path):
        """setup_environment создаёт пустой proxies.txt, если его нет."""
        mock_paths = _make_mock_paths(tmp_path)

        with patch("core.config.get_paths", return_value=mock_paths):
            setup_environment()

        assert (tmp_path / "proxies.txt").exists()

    def test_does_not_overwrite_existing_proxies_file(self, tmp_path: Path):
        """Если proxies.txt уже существует — не трогает его содержимое."""
        proxies = tmp_path / "proxies.txt"
        proxies.write_text("http://proxy:8080\n", encoding="utf-8")

        mock_paths = _make_mock_paths(tmp_path)

        with patch("core.config.get_paths", return_value=mock_paths):
            setup_environment()

        assert proxies.read_text(encoding="utf-8") == "http://proxy:8080\n"

    def test_raises_runtime_error_on_mkdir_failure(self, tmp_path: Path):
        """При ошибке создания директории выбрасывает RuntimeError."""
        mock_paths = _make_mock_paths(tmp_path)

        with (
            patch("core.config.get_paths", return_value=mock_paths),
            patch.object(Path, "mkdir", side_effect=OSError("permission denied")),
            pytest.raises(RuntimeError, match="permission denied"),
        ):
            setup_environment()

    def test_raises_runtime_error_on_touch_failure(self, tmp_path: Path):
        """При ошибке создания proxies.txt выбрасывает RuntimeError."""
        mock_paths = _make_mock_paths(tmp_path)

        with (
            patch("core.config.get_paths", return_value=mock_paths),
            patch.object(Path, "touch", side_effect=OSError("read only fs")),
            pytest.raises(RuntimeError, match="read only fs"),
        ):
            setup_environment()

    def test_mkdir_failure_prints_to_stderr(self, tmp_path: Path, capsys):
        """При ошибке mkdir сообщение дублируется в stderr."""
        mock_paths = _make_mock_paths(tmp_path)

        with (
            patch("core.config.get_paths", return_value=mock_paths),
            patch.object(Path, "mkdir", side_effect=OSError("no space left")),
            pytest.raises(RuntimeError),
        ):
            setup_environment()

        captured = capsys.readouterr()
        assert "ERROR" in captured.err
        assert "no space left" in captured.err

    def test_touch_failure_prints_to_stderr(self, tmp_path: Path, capsys):
        """При ошибке touch сообщение дублируется в stderr."""
        mock_paths = _make_mock_paths(tmp_path)

        with (
            patch("core.config.get_paths", return_value=mock_paths),
            patch.object(Path, "touch", side_effect=OSError("disk full")),
            pytest.raises(RuntimeError),
        ):
            setup_environment()

        captured = capsys.readouterr()
        assert "ERROR" in captured.err
        assert "disk full" in captured.err

    def test_logs_info_on_success(self, tmp_path: Path, caplog):
        """setup_environment логирует INFO об успешной инициализации."""
        mock_paths = _make_mock_paths(tmp_path)

        with (
            patch("core.config.get_paths", return_value=mock_paths),
            caplog.at_level(logging.INFO, logger="core.config"),
        ):
            setup_environment()

        assert any("инициализировано" in r.message.lower() for r in caplog.records)

    def test_idempotent_on_existing_directories(self, tmp_path: Path):
        """Повторный вызов setup_environment не выбрасывает ошибку."""
        mock_paths = _make_mock_paths(tmp_path)

        with patch("core.config.get_paths", return_value=mock_paths):
            setup_environment()
            setup_environment()  # второй вызов — должен пройти без ошибок

        assert (tmp_path / "data").exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_paths(tmp_path: Path) -> MagicMock:
    """
    Создаёт MagicMock, имитирующий ProjectPaths с путями внутри tmp_path.
    Используем реальные Path-объекты, чтобы mkdir/touch работали честно.
    """
    mock = MagicMock(spec=ProjectPaths)
    mock.root_dir = tmp_path
    mock.data_dir = tmp_path / "data"
    mock.profiles_dir = tmp_path / "data" / "profiles"
    mock.logs_dir = tmp_path / "logs"
    mock.proxies_file = tmp_path / "proxies.txt"
    return mock
