"""
Исполнители (Executors) парсинга.
Реализуют процесс обхода страниц (Crawling) и извлечения данных (Scraping).

Доступные стратегии:
- LightExecutor: Легкий парсер на базе curl_cffi (подмена TLS). 10 МБ ОЗУ.
- StealthExecutor: Тяжелый парсер на базе Camoufox (Playwright). 200 МБ ОЗУ.
"""

from .base import ExecutorStats, IExecutor, SaveCallback
from .light import LightExecutor
from .stealth import StealthExecutor

__all__ = [
    "ExecutorStats",
    "IExecutor",
    "LightExecutor",
    "SaveCallback",
    "StealthExecutor",
]
