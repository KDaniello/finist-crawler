import logging
import os
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)

__all__ = ["SystemMonitor", "SystemStats"]


@dataclass(frozen=True)
class SystemStats:
    """Неизменяемый (frozen) объект со статистикой системы. Безопасен для передачи между потоками."""

    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    app_memory_mb: float


class SystemMonitor:
    """
    Облегченный монитор ресурсов ПК.
    Не содержит глобального состояния. Должен инстанцироваться в UI,
    который будет периодически вызывать get_stats().
    """

    def __init__(self) -> None:
        # Кэшируем объект текущего процесса один раз при создании.
        # Это экономит 1 тяжелый системный вызов (syscall) на каждый тик мониторинга.
        self._main_process = psutil.Process(os.getpid())

        # Инициализируем CPU-таймер. interval=None делает вызов неблокирующим.
        # При первом вызове он запоминает счетчики ядра ОС, чтобы последующие вызовы
        # в get_stats() могли вычислить дельту загрузки процессора.
        psutil.cpu_percent(interval=None)

    def get_stats(self) -> SystemStats:
        """Возвращает текущую статистику системы."""
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            app_mem = self._get_total_app_memory()

            return SystemStats(
                cpu_percent=round(cpu, 1),
                ram_percent=round(mem.percent, 1),
                ram_used_gb=round(mem.used / (1024**3), 2),
                ram_total_gb=round(mem.total / (1024**3), 2),
                app_memory_mb=app_mem,
            )
        except Exception as e:
            logger.debug(f"Ошибка получения системной статистики: {e}")
            # Graceful Degradation: возвращаем нули, не ломая UI-поток
            return SystemStats(0.0, 0.0, 0.0, 0.0, 0.0)

    def _get_total_app_memory(self) -> float:
        """
        Считает RSS (Resident Set Size - физически занятую ОЗУ) главного процесса
        и всех его дочерних воркеров (включая ветвистые процессы браузера Camoufox).
        """
        try:
            total_bytes = self._main_process.memory_info().rss

            # recursive=True критически важно для Playwright, так как он плодит
            # процессы (Broker, Utility, Renderer) в глубину дерева процессов.
            children = self._main_process.children(recursive=True)

            for child in children:
                try:
                    total_bytes += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Процесс мог успеть умереть между вызовом .children() и .memory_info()
                    continue

            return round(total_bytes / (1024**2), 2)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0
        except Exception as e:
            logger.debug(f"Неожиданная ошибка при подсчете памяти приложения: {e}")
            return 0.0
