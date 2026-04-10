import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from jsonschema.exceptions import ValidationError
from yaml.error import YAMLError

logger = logging.getLogger(__name__)

__all__ = ["SpecError", "load_spec"]


class SpecError(Exception):
    """Кастомное исключение для ошибок загрузки и валидации спецификаций."""


@lru_cache(maxsize=1)
def _load_schema(specs_dir: Path) -> dict[str, Any]:
    """
    Загружает и кэширует JSON Schema валидатор.
    Вызывается только один раз за время жизни процесса-воркера.
    """
    schema_path = specs_dir / "schema.json"

    if not schema_path.exists():
        logger.warning(f"Файл схемы не найден по пути: {schema_path}. Валидация отключена.")
        return {}

    try:
        raw = schema_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Схема должна быть JSON-словарем.")
        return data
    except Exception as e:
        logger.error(f"Ошибка чтения schema.json: {e}")
        return {}


def _format_validation_error(e: ValidationError) -> str:
    """
    Превращает техническую ошибку jsonschema в понятную для гуманитария.
    Например: "$.crawler.list.pagination.scroll_by_px должно быть >= 200".
    """
    # Собираем путь к проблемному полю (например: crawler -> list -> fields)
    path = " -> ".join([str(p) for p in e.path]) if e.path else "Корень файла"

    # Форматируем сообщение
    base_msg = f"Ошибка в поле [{path}]:\n- {e.message}"

    # Добавляем контекст (что ожидалось)
    if e.validator == "required":
        return f"Отсутствует обязательное поле: {e.message}"
    if e.validator == "enum":
        allowed = (
            ", ".join(map(str, e.validator_value))
            if isinstance(e.validator_value, list)
            else str(e.validator_value)
        )
        return f"{base_msg}\n- Допустимые значения: {allowed}"
    if e.validator == "type":
        return f"{base_msg}\n- Ожидаемый тип данных: {e.validator_value}"

    return base_msg


@lru_cache(maxsize=32)
def load_spec(spec_name: str, specs_dir: Path) -> dict[str, Any]:
    """
    Загружает, парсит YAML и валидирует его по schema.json.
    Использует lru_cache для экономии I/O.
    """
    # 1. Нормализация имени и поиск файла
    if not (spec_name.endswith(".yaml") or spec_name.endswith(".yml")):
        spec_name += ".yaml"

    target_path: Path = specs_dir / spec_name

    if not target_path.exists() and target_path.suffix == ".yaml":
        alt_path = target_path.with_suffix(".yml")
        if alt_path.exists():
            target_path = alt_path

    if not target_path.exists():
        raise SpecError(f"Файл спецификации не найден: {target_path.name}")

    # 2. Парсинг YAML
    try:
        raw_content = target_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_content)
    except YAMLError as e:
        logger.error(f"Синтаксическая ошибка YAML в {target_path.name}:\n{e}")
        raise SpecError(f"Ошибка формата в файле {target_path.name}. Проверьте отступы.") from e
    except Exception as e:
        raise SpecError(f"Не удалось прочитать файл {target_path.name}: {e}") from e

    if not isinstance(data, dict):
        raise SpecError(f"Спецификация {target_path.name} должна быть словарем.")

    # 3. Валидация по JSON Schema
    schema = _load_schema(specs_dir)
    if schema:
        try:
            jsonschema.validate(instance=data, schema=schema)
            logger.debug(f"Спецификация {target_path.name} успешно прошла валидацию.")
        except ValidationError as e:
            friendly_msg = _format_validation_error(e)
            logger.error(f"Спецификация {target_path.name} невалидна:\n{friendly_msg}")
            raise SpecError(f"Ошибка конфигурации в {target_path.name}:\n{friendly_msg}") from e

    return data
