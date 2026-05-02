# mypy: disable-error-code=no-untyped-def
# ruff: noqa: RUF002

"""
Тесты для core/resources.py

Покрытие: 100%
- SystemStats: проверка неизменяемости (frozen).
- SystemMonitor __init__: проверка кэширования текущего процесса и "прогрева" счетчика CPU.
- get_stats (Success): правильная математика конвертации байтов в гигабайты и мегабайты.
- get_stats (Graceful Degradation): обработка глобальных ошибок с возвратом нулей.
- _get_total_app_memory (Success): рекурсивный обход детей.
- _get_total_app_memory (Dead Child): игнорирование умерших процессов (NoSuchProcess/AccessDenied).
- _get_total_app_memory (Dead Main): перехват смерти главного процесса (возврат 0.0).
- _get_total_app_memory (Unexpected Error): перехват неизвестных ошибок (возврат 0.0).
"""

import logging
from collections import namedtuple
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import psutil
import pytest

from core.resources import SystemMonitor, SystemStats

# ---------------------------------------------------------------------------
# Dummies & Fixtures
# ---------------------------------------------------------------------------

# Имитация ответа от psutil.virtual_memory
VirtualMemoryMock = namedtuple("VirtualMemoryMock", ["total", "used", "percent"])


@pytest.fixture
def mock_psutil_process():
    """Мокает конструктор psutil.Process для изоляции тестов от ОС."""
    with patch("psutil.Process") as mock_process_cls:
        main_proc = MagicMock()
        mock_process_cls.return_value = main_proc
        yield main_proc


@pytest.fixture
def monitor(mock_psutil_process):
    """Инициализирует SystemMonitor с замоканным psutil.Process и cpu_percent."""
    with patch("psutil.cpu_percent"):
        return SystemMonitor()


# ---------------------------------------------------------------------------
# SystemStats Tests
# ---------------------------------------------------------------------------


class TestSystemStats:
    def test_stats_is_frozen(self):
        """SystemStats должен быть frozen dataclass для потокобезопасности."""
        stats = SystemStats(
            cpu_percent=10.0,
            ram_percent=50.0,
            ram_used_gb=8.0,
            ram_total_gb=16.0,
            app_memory_mb=100.0,
        )

        with pytest.raises(FrozenInstanceError):
            stats.cpu_percent = 20.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SystemMonitor Initialization Tests
# ---------------------------------------------------------------------------


class TestSystemMonitorInit:
    @patch("os.getpid", return_value=12345)
    @patch("psutil.Process")
    @patch("psutil.cpu_percent")
    def test_init_caches_process_and_warms_cpu(self, mock_cpu, mock_process, mock_getpid):
        """__init__ кэширует процесс по PID и делает неблокирующий вызов cpu_percent."""
        monitor = SystemMonitor()

        mock_getpid.assert_called_once()
        mock_process.assert_called_once_with(12345)
        assert monitor._main_process == mock_process.return_value

        # Проверка прогрева счетчика CPU
        mock_cpu.assert_called_once_with(interval=None)


# ---------------------------------------------------------------------------
# SystemMonitor get_stats Tests
# ---------------------------------------------------------------------------


class TestSystemMonitorGetStats:
    @patch("psutil.cpu_percent", return_value=25.67)
    @patch(
        "psutil.virtual_memory",
        return_value=VirtualMemoryMock(
            total=16 * (1024**3),  # 16 GB
            used=8 * (1024**3),  # 8 GB
            percent=50.12,
        ),
    )
    def test_get_stats_success(self, mock_vmem, mock_cpu, monitor):
        """get_stats корректно округляет данные и конвертирует байты в ГБ/МБ."""
        with patch.object(monitor, "_get_total_app_memory", return_value=150.75):
            stats = monitor.get_stats()

        assert stats.cpu_percent == 25.7  # 25.67 -> 25.7
        assert stats.ram_percent == 50.1  # 50.12 -> 50.1
        assert stats.ram_used_gb == 8.0  # 8 GB
        assert stats.ram_total_gb == 16.0  # 16 GB
        assert stats.app_memory_mb == 150.75

        mock_cpu.assert_called_with(interval=None)

    @patch("psutil.cpu_percent", side_effect=Exception("System metrics blocked by Antivirus"))
    def test_get_stats_graceful_degradation(self, mock_cpu, monitor, caplog):
        """При любых глобальных ошибках ОС возвращаются нули (UI не падает)."""
        with caplog.at_level(logging.DEBUG):
            stats = monitor.get_stats()

        assert stats.cpu_percent == 0.0
        assert stats.ram_percent == 0.0
        assert stats.ram_used_gb == 0.0
        assert stats.ram_total_gb == 0.0
        assert stats.app_memory_mb == 0.0

        assert "Ошибка получения системной статистики" in caplog.text
        assert "System metrics blocked" in caplog.text


# ---------------------------------------------------------------------------
# SystemMonitor _get_total_app_memory Tests
# ---------------------------------------------------------------------------


class TestSystemMonitorGetAppMemory:
    def test_memory_success(self, monitor, mock_psutil_process):
        """Корректный подсчет памяти: главный процесс + рекурсивно все дети."""
        # Главный процесс занимает 100 MB
        main_mem = MagicMock()
        main_mem.rss = 100 * (1024**2)
        mock_psutil_process.memory_info.return_value = main_mem

        # Ребенок 1 занимает 50 MB
        child1 = MagicMock()
        child1.memory_info.return_value.rss = 50 * (1024**2)

        # Ребенок 2 занимает 25 MB
        child2 = MagicMock()
        child2.memory_info.return_value.rss = 25 * (1024**2)

        mock_psutil_process.children.return_value = [child1, child2]

        total_mb = monitor._get_total_app_memory()

        assert total_mb == 175.0  # 100 + 50 + 25
        mock_psutil_process.children.assert_called_once_with(recursive=True)

    def test_memory_ignores_dead_children(self, monitor, mock_psutil_process):
        """Если ребенок умер до вызова memory_info (NoSuchProcess), он пропускается."""
        main_mem = MagicMock()
        main_mem.rss = 100 * (1024**2)
        mock_psutil_process.memory_info.return_value = main_mem

        # Живой ребенок
        child_alive = MagicMock()
        child_alive.memory_info.return_value.rss = 50 * (1024**2)

        # Мертвый ребенок
        child_dead = MagicMock()
        child_dead.memory_info.side_effect = psutil.NoSuchProcess(pid=999)

        # Ребенок, к которому закрыт доступ
        child_denied = MagicMock()
        child_denied.memory_info.side_effect = psutil.AccessDenied(pid=888)

        mock_psutil_process.children.return_value = [child_alive, child_dead, child_denied]

        total_mb = monitor._get_total_app_memory()

        # 100 (main) + 50 (alive) = 150. Ошибки мертвого и закрытого игнорируются.
        assert total_mb == 150.0

    def test_memory_main_process_dead(self, monitor, mock_psutil_process):
        """Если сам главный процесс внезапно умирает, возвращается 0.0."""
        mock_psutil_process.memory_info.side_effect = psutil.NoSuchProcess(pid=123)

        total_mb = monitor._get_total_app_memory()
        assert total_mb == 0.0

    def test_memory_unexpected_error(self, monitor, mock_psutil_process, caplog):
        """Если возникает неведомая ошибка (например OSError), возвращается 0.0."""
        mock_psutil_process.memory_info.side_effect = OSError("Unknown System Error")

        with caplog.at_level(logging.DEBUG):
            total_mb = monitor._get_total_app_memory()

        assert total_mb == 0.0
        assert "Неожиданная ошибка при подсчете памяти" in caplog.text
