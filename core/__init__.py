"""
Ядро системы Finist (Core Module).
Обеспечивает базовый системный функционал:
управление путями, конфигурацию, потокобезопасное логирование,
работу с файлами (JSONL/CSV/XLSX), диспетчеризацию процессов и автообновления (OTA).

Архитектура: Dependency Injection, Zero Global State.
"""

from .config import ProjectPaths, Settings, get_paths, get_settings, setup_environment
from .dispatcher import Dispatcher, WorkerCallable
from .exceptions import (
    CaptchaBlockError,
    ConfigurationError,
    FinistError,
    NetworkError,
    ParsingError,
    RateLimitError,
)
from .file_manager import DataWriter, SessionManager
from .job_config import JobConfig
from .logger import LogManager, setup_worker_logging
from .resources import SystemMonitor
from .telemetry import TelemetryEvent, TelemetryEventType
from .updater import SpecUpdater

__all__ = [
    "CaptchaBlockError",
    "ConfigurationError",
    "DataWriter",
    "Dispatcher",
    "FinistError",
    "JobConfig",
    "LogManager",
    "NetworkError",
    "ParsingError",
    "ProjectPaths",
    "RateLimitError",
    "SessionManager",
    "Settings",
    "SpecUpdater",
    "SystemMonitor",
    "TelemetryEvent",
    "TelemetryEventType",
    "WorkerCallable",
    "get_paths",
    "get_settings",
    "setup_environment",
    "setup_worker_logging",
]
