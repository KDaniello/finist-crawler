"""
Глобальная конфигурация для всех Unit-тестов.
Отключает загрузку тяжелых C-библиотек и браузеров,
чтобы юнит-тесты были быстрыми и не падали на импортах (особенно numpy/camoufox).
"""

import sys
from unittest.mock import MagicMock

# Создаем единый пустой мок
mock_pkg = MagicMock()

# Подменяем тяжелые модули в sys.modules ДО того, как pytest начнет импортировать файлы проекта
heavy_modules = [
    "camoufox",
    "camoufox.async_api",
    "playwright",
    "playwright.async_api",
    "numpy",
    "numpy._core",
]

for mod in heavy_modules:
    sys.modules[mod] = mock_pkg
