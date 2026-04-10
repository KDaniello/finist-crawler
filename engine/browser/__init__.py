"""
Модуль Browser (Stealth & Anti-Detect).
Обеспечивает управление тяжелыми браузерными сессиями (Camoufox/Playwright),
имитацию поведения человека (HumanBehavior) и систему ротации профилей.

Архитектура:
- behaviors.py: Кривые Безье, рандомизация мыши и скролла.
- browser_setup.py: Конфигурация LEAN_PREFS, управление ресурсами и перехват сети.
- detection.py: Быстрые JS-скрипты для детекта Cloudflare/DataDome.
- profiles.py: Файловое хранилище состояний сессий (вместо SQL/Redis).
"""

from .behaviors import HumanBehavior
from .browser_setup import LEAN_PREFS, ImmortalBrowser
from .detection import is_captcha_page
from .profiles import (
    ProfileManager,
    SessionConfig,
    SessionHealth,
    SessionState,
    SessionStats,
)

__all__ = [
    "LEAN_PREFS",
    "HumanBehavior",
    "ImmortalBrowser",
    "ProfileManager",
    "SessionConfig",
    "SessionHealth",
    "SessionState",
    "SessionStats",
    "is_captcha_page",
]
