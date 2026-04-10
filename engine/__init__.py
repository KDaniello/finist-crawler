"""
Движок парсинга (Parsing Engine).
Отвечает за загрузку правил, извлечение данных, троттлинг запросов и
оркестрацию исполнителей (Light/Stealth) через цепочку Fallback.

Архитектура:
- spec_loader.py: Загрузчик и валидатор YAML-спецификаций (jsonschema).
- parsing_rules.py: Парсинг HTML/JSON, JMESPath, BS4, стратегия извлечения.
- rate_limiter.py: Локальный TokenBucket для контроля скорости (Anti-Ban).
- fallback_chain.py: Оркестратор деградации (curl_cffi -> Camoufox).
- executors/: Физические исполнители HTTP-запросов и рендеринга.
- browser/: Управление жизненным циклом и профилями Camoufox.
"""

from .fallback_chain import FallbackOrchestrator
from .parsing_rules import CrawlerPlan, FieldRule, build_plan
from .rate_limiter import DomainConfig, TokenBucket
from .spec_loader import SpecError, load_spec

__all__ = [
    "CrawlerPlan",
    "DomainConfig",
    "FallbackOrchestrator",
    "FieldRule",
    "SpecError",
    "TokenBucket",
    "build_plan",
    "load_spec",
]
