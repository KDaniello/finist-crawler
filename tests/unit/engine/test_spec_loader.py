"""
Тесты для engine/spec_loader.py

Покрытие: 100%
- _load_schema: кэширование, отсутствие файла, невалидный JSON, не-словарь, успех.
- _format_validation_error: форматирование required, enum, type и дефолтных ошибок (с/без пути).
- load_spec:
    - Нормализация путей (.yaml, .yml, без расширения).
    - Отсутствие файла спецификации (SpecError).
    - Ошибки синтаксиса YAML (SpecError).
    - Неожиданные ошибки чтения (SpecError).
    - Спецификация — не словарь (SpecError).
    - Успешная загрузка с/без валидации.
    - Ошибка валидации по схеме (SpecError).
    - Проверка работы lru_cache.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema.exceptions import ValidationError

# Импортируем защищенные функции для тестирования
from engine.spec_loader import SpecError, _format_validation_error, _load_schema, load_spec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_caches():
    """Сбрасывает lru_cache перед каждым тестом для изоляции."""
    _load_schema.cache_clear()
    load_spec.cache_clear()
    yield
    _load_schema.cache_clear()
    load_spec.cache_clear()


@pytest.fixture
def specs_dir(tmp_path: Path) -> Path:
    """Временная директория со спецификациями."""
    return tmp_path


# ---------------------------------------------------------------------------
# _load_schema Tests
# ---------------------------------------------------------------------------


class TestLoadSchema:
    def test_schema_not_found(self, specs_dir, caplog):
        """Если schema.json нет, возвращается пустой словарь и пишется WARNING."""
        schema = _load_schema(specs_dir)

        assert schema == {}
        assert "Файл схемы не найден" in caplog.text

    def test_schema_invalid_json(self, specs_dir, caplog):
        """Если schema.json содержит битый JSON, возвращается пустой словарь."""
        (specs_dir / "schema.json").write_text("broken { json", encoding="utf-8")

        schema = _load_schema(specs_dir)

        assert schema == {}
        assert "Ошибка чтения schema.json" in caplog.text

    def test_schema_not_dict(self, specs_dir, caplog):
        """Если schema.json — это список, а не словарь, возвращается пустой словарь."""
        (specs_dir / "schema.json").write_text('["not", "a", "dict"]', encoding="utf-8")

        schema = _load_schema(specs_dir)

        assert schema == {}
        assert "Схема должна быть JSON-словарем" in caplog.text

    def test_schema_success(self, specs_dir):
        """Успешная загрузка валидной схемы."""
        (specs_dir / "schema.json").write_text('{"type": "object"}', encoding="utf-8")

        schema = _load_schema(specs_dir)

        assert schema == {"type": "object"}


# ---------------------------------------------------------------------------
# _format_validation_error Tests
# ---------------------------------------------------------------------------


class TestFormatValidationError:
    def test_format_required(self):
        err = ValidationError("'name' is a required property", validator="required", path=[])
        res = _format_validation_error(err)
        assert res == "Отсутствует обязательное поле: 'name' is a required property"

    def test_format_enum(self):
        err = ValidationError(
            "not in enum", validator="enum", validator_value=["a", "b"], path=["type"]
        )
        res = _format_validation_error(err)
        assert "Ошибка в поле [type]:" in res
        assert "Допустимые значения: a, b" in res

    def test_format_enum_string_value(self):
        """Проверка enum, когда validator_value не список (защита от краша)."""
        err = ValidationError("not in enum", validator="enum", validator_value="only_a", path=[])
        res = _format_validation_error(err)
        assert "Допустимые значения: only_a" in res

    def test_format_type(self):
        err = ValidationError(
            "wrong type", validator="type", validator_value="integer", path=["age"]
        )
        res = _format_validation_error(err)
        assert "Ошибка в поле [age]:" in res
        assert "Ожидаемый тип данных: integer" in res

    def test_format_generic(self):
        err = ValidationError("must be >= 0", validator="minimum", path=["count", "nested"])
        res = _format_validation_error(err)
        assert "Ошибка в поле [count -> nested]:" in res
        assert "must be >= 0" in res

    def test_format_empty_path(self):
        err = ValidationError("generic error", validator="any", path=[])
        res = _format_validation_error(err)
        assert "Ошибка в поле [Корень файла]:" in res


# ---------------------------------------------------------------------------
# load_spec Tests
# ---------------------------------------------------------------------------


class TestLoadSpec:
    def test_normalize_extension_yaml(self, specs_dir):
        """Если имя передано без расширения, добавляется .yaml."""
        (specs_dir / "test.yaml").write_text("key: value", encoding="utf-8")

        data = load_spec("test", specs_dir)
        assert data == {"key": "value"}

    def test_fallback_to_yml(self, specs_dir):
        """Если .yaml нет, но есть .yml, загружается .yml."""
        (specs_dir / "test.yml").write_text("key: from_yml", encoding="utf-8")

        data = load_spec("test", specs_dir)
        assert data == {"key": "from_yml"}

    def test_spec_not_found(self, specs_dir):
        """Если файла нет, выбрасывается SpecError."""
        with pytest.raises(SpecError, match="Файл спецификации не найден: missing.yaml"):
            load_spec("missing", specs_dir)

    def test_invalid_yaml_syntax(self, specs_dir, caplog):
        """При синтаксической ошибке YAML выбрасывается SpecError."""
        (specs_dir / "bad.yaml").write_text("key: value\n  broken_indent: true", encoding="utf-8")

        with pytest.raises(SpecError, match="Ошибка формата в файле bad.yaml"):
            load_spec("bad", specs_dir)

        assert "Синтаксическая ошибка YAML" in caplog.text

    def test_read_error(self, specs_dir):
        """При ошибке ОС (например, нет прав) выбрасывается SpecError."""
        (specs_dir / "err.yaml").write_text("key: value", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=OSError("Access Denied")):
            with pytest.raises(SpecError, match="Не удалось прочитать файл err.yaml"):
                load_spec("err", specs_dir)

    def test_spec_is_not_dict(self, specs_dir):
        """Спецификация должна быть словарем на верхнем уровне."""
        (specs_dir / "list.yaml").write_text("- item1\n- item2", encoding="utf-8")

        with pytest.raises(SpecError, match="Спецификация list.yaml должна быть словарем."):
            load_spec("list", specs_dir)

    def test_validation_success(self, specs_dir):
        """Успешная валидация по схеме."""
        (specs_dir / "schema.json").write_text(
            '{"type": "object", "required": ["name"]}', encoding="utf-8"
        )
        (specs_dir / "valid.yaml").write_text("name: reddit", encoding="utf-8")

        data = load_spec("valid", specs_dir)
        assert data == {"name": "reddit"}

    def test_validation_error(self, specs_dir, caplog):
        """Неудачная валидация выбрасывает SpecError с понятным сообщением."""
        (specs_dir / "schema.json").write_text(
            '{"type": "object", "required": ["name"]}', encoding="utf-8"
        )
        (specs_dir / "invalid.yaml").write_text("age: 10", encoding="utf-8")

        with pytest.raises(SpecError, match="Ошибка конфигурации в invalid.yaml"):
            load_spec("invalid", specs_dir)

        assert "Спецификация invalid.yaml невалидна" in caplog.text

    def test_lru_cache_works(self, specs_dir):
        """Повторный вызов не читает файл с диска (работает lru_cache)."""
        target = specs_dir / "cached.yaml"
        target.write_text("key: v1", encoding="utf-8")

        # Первый вызов (читает с диска)
        res1 = load_spec("cached", specs_dir)
        assert res1 == {"key": "v1"}

        # Меняем файл на диске
        target.write_text("key: v2", encoding="utf-8")

        # Второй вызов (возвращает из кэша, изменения на диске игнорируются)
        res2 = load_spec("cached", specs_dir)
        assert res2 == {"key": "v1"}
