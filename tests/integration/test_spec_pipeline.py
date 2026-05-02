"""
Интеграционный тест конвейера спецификаций (Spec Pipeline).

Проверяет реальное взаимодействие:
YAML-файл на диске -> load_spec (парсинг + валидация по schema.json) -> build_plan -> CrawlerPlan

Мы не мокаем ни файловую систему, ни валидатор.
Все YAML и schema.json создаются во временной директории как реальные файлы.
"""

import json
from pathlib import Path

import pytest
import yaml

from engine.parsing_rules import CrawlerPlan, build_plan
from engine.spec_loader import SpecError, _load_schema, load_spec

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
    """Создает временную директорию для хранения спецификаций."""
    d = tmp_path / "specs"
    d.mkdir()
    return d


@pytest.fixture
def schema_file(specs_dir: Path) -> Path:
    """Копирует наш реальный schema.json во временную директорию."""
    # Ищем schema.json относительно корня проекта
    real_schema = Path(__file__).resolve().parent.parent.parent / "specs" / "schema.json"

    if real_schema.exists():
        schema_data = json.loads(real_schema.read_text(encoding="utf-8"))
    else:
        # Если файл еще не в проекте, используем минимальную схему для тестов
        schema_data = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["source_key", "version", "flow"],
            "properties": {
                "source_key": {"type": "string", "minLength": 1},
                "version": {"type": "string", "minLength": 1},
                "flow": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "string",
                        "enum": ["seed", "list", "detail", "extract", "postprocess"],
                    },
                },
                "crawler": {
                    "type": "object",
                    "properties": {
                        "render": {"type": "string", "enum": ["browser", "static", "auto"]},
                        "list": {
                            "type": "object",
                            "required": ["item_selector", "fields"],
                            "properties": {
                                "start_urls": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string"},
                                },
                                "item_selector": {"type": "string", "minLength": 1},
                                "extraction_mode": {"type": "string", "enum": ["html", "json"]},
                                "fields": {"type": "object"},
                                "next_page": {"type": "object"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": True,
        }

    schema_path = specs_dir / "schema.json"
    schema_path.write_text(json.dumps(schema_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return schema_path


@pytest.fixture
def valid_spec_content() -> dict:
    """Возвращает словарь с полной и валидной спецификацией."""
    return {
        "source_key": "test_forum",
        "version": "1.0.0",
        "description": "Тестовый форум для интеграционных тестов",
        "flow": ["list"],
        "crawler": {
            "render": "static",
            "limits": {
                "max_pages": 10,
            },
            "list": {
                "start_urls": ["https://test-forum.com/reviews"],
                "item_selector": ".review-item",
                "extraction_mode": "html",
                "fields": {
                    "external_id": {"selector": "[data-id]", "attr": "data-id"},
                    "text": ".review-text",
                    "author": {"selector": ".author-name", "default": "Аноним"},
                    "rating": ".star-rating",
                    "created_at": "time",
                },
                "next_page": {"selector": ".pagination-next", "attr": "href"},
            },
        },
    }


# ---------------------------------------------------------------------------
# Load Spec Tests
# ---------------------------------------------------------------------------


class TestLoadSpecIntegration:
    def test_load_valid_yaml_with_schema(self, specs_dir, schema_file, valid_spec_content):
        """Реальная загрузка валидного YAML с проверкой по schema.json."""
        spec_path = specs_dir / "test_forum.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        data = load_spec("test_forum", specs_dir)

        assert data["source_key"] == "test_forum"
        assert data["version"] == "1.0.0"
        assert "crawler" in data

    def test_load_spec_with_yml_extension(self, specs_dir, schema_file, valid_spec_content):
        """Загрузка файла с расширением .yml (не .yaml)."""
        spec_path = specs_dir / "test_forum.yml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        data = load_spec("test_forum", specs_dir)
        assert data["source_key"] == "test_forum"

    def test_load_spec_missing_required_field(self, specs_dir, schema_file):
        """YAML без обязательного поля 'version' должен провалить валидацию."""
        invalid_spec = {
            "source_key": "broken",
            # Нет "version" и "flow" - нарушение схемы
            "crawler": {},
        }
        spec_path = specs_dir / "broken.yaml"
        spec_path.write_text(yaml.dump(invalid_spec), encoding="utf-8")

        with pytest.raises(SpecError, match="Ошибка конфигурации"):
            load_spec("broken", specs_dir)

    def test_load_spec_invalid_enum(self, specs_dir, schema_file, valid_spec_content):
        """Неверное значение enum (например, render='magic') должно провалить валидацию."""
        valid_spec_content["crawler"]["render"] = "magic"  # Не из enum

        spec_path = specs_dir / "bad_enum.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        with pytest.raises(SpecError, match="Ошибка конфигурации"):
            load_spec("bad_enum", specs_dir)

    def test_load_spec_not_found(self, specs_dir, schema_file):
        """Несуществующий файл должен давать SpecError."""
        with pytest.raises(SpecError, match="Файл спецификации не найден"):
            load_spec("ghost_spec", specs_dir)

    def test_load_spec_invalid_yaml_syntax(self, specs_dir, schema_file):
        """Файл с синтаксической ошибкой YAML должен давать SpecError."""
        bad_yaml = "key: value\n  broken_indent: true\n  another: broken"
        spec_path = specs_dir / "bad_syntax.yaml"
        spec_path.write_text(bad_yaml, encoding="utf-8")

        with pytest.raises(SpecError, match="Ошибка формата"):
            load_spec("bad_syntax", specs_dir)

    def test_load_spec_without_schema(self, specs_dir, valid_spec_content):
        """Если schema.json отсутствует, загрузка работает без валидации (graceful degradation)."""
        # schema.json НЕ создаем в specs_dir
        spec_path = specs_dir / "no_schema.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        # Должно сработать без ошибок
        data = load_spec("no_schema", specs_dir)
        assert data["source_key"] == "test_forum"

    def test_load_spec_caches_result(self, specs_dir, schema_file, valid_spec_content):
        """Повторный вызов возвращает тот же объект из кэша."""
        spec_path = specs_dir / "cached.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        result1 = load_spec("cached", specs_dir)
        # Меняем файл на диске
        valid_spec_content["version"] = "9.9.9"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        result2 = load_spec("cached", specs_dir)
        # Версия не должна измениться (кэш работает)
        assert result2["version"] == "1.0.0"
        assert result1 is result2


# ---------------------------------------------------------------------------
# Build Plan Tests
# ---------------------------------------------------------------------------


class TestBuildPlanIntegration:
    def test_build_plan_full_pipeline(self, specs_dir, schema_file, valid_spec_content):
        """
        Полный интеграционный тест:
        YAML на диске -> load_spec -> build_plan -> CrawlerPlan.
        Проверяем, что все поля правильно прошли через весь стек.
        """
        spec_path = specs_dir / "full_pipeline.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        # Шаг 1: Загрузка с диска
        spec_data = load_spec("full_pipeline", specs_dir)

        # Шаг 2: Построение плана без переопределений
        plan = build_plan(spec_data, config_overrides={})

        # Проверяем результат
        assert isinstance(plan, CrawlerPlan)
        assert plan.start_urls == ["https://test-forum.com/reviews"]
        assert plan.item_selector == ".review-item"
        assert plan.extraction_mode == "html"
        assert plan.next_page_selector == ".pagination-next"
        assert plan.next_page_attr == "href"

        # Проверяем поля
        assert "text" in plan.fields
        assert "author" in plan.fields
        assert "rating" in plan.fields
        assert "external_id" in plan.fields

        # Проверяем FieldRule для author (у него есть дефолт)
        author_rule = plan.fields["author"]
        assert author_rule.selector == ".author-name"
        assert author_rule.default == "Аноним"

        # Проверяем FieldRule для external_id (у него есть attr)
        ext_id_rule = plan.fields["external_id"]
        assert ext_id_rule.attr == "data-id"

    def test_build_plan_with_overrides(self, specs_dir, schema_file, valid_spec_content):
        """
        Проверяет, что config_overrides из UI корректно переопределяют значения из YAML.
        Это ключевая функция: пользователь вводит URL в UI, он должен иметь приоритет.
        """
        spec_path = specs_dir / "override_test.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        spec_data = load_spec("override_test", specs_dir)

        # Пользователь вводит другие URL через UI
        overrides = {"start_urls": ["https://custom-user-input.com/page/1"], "max_pages": 3}
        plan = build_plan(spec_data, config_overrides=overrides)

        assert plan.start_urls == ["https://custom-user-input.com/page/1"]
        assert plan.max_pages == 3

    def test_build_plan_success_with_url_template(self, specs_dir, schema_file):
        """
        Если в YAML есть url_template с параметрами и переданы template_params,
        build_plan форматирует URL и возвращает заполненный start_urls.
        """
        spec_no_start_urls = {
            "source_key": "no_start_urls",
            "version": "1.0",
            "flow": ["list"],
            "crawler": {
                "list": {
                    "url_template": "https://example.com/{branch_id}/reviews",
                    "item_selector": ".item",
                    "fields": {"text": ".text"},
                }
            },
        }
        spec_path = specs_dir / "no_start_urls.yaml"
        spec_path.write_text(yaml.dump(spec_no_start_urls), encoding="utf-8")

        spec_data = load_spec("no_start_urls", specs_dir)

        plan = build_plan(
            spec_data,
            config_overrides={"template_params": {"branch_id": "123"}},
        )

        assert plan.start_urls == ["https://example.com/123/reviews"]
        assert plan.url_template == "https://example.com/{branch_id}/reviews"

    def test_build_plan_raises_without_any_urls(self):
        """
        Прямая проверка движка: если нет ни start_urls, ни url_template,
        build_plan должен выбросить ValueError (страховочная сетка на случай обхода валидатора).
        """
        spec_data = {
            "crawler": {
                "list": {
                    "item_selector": ".item",
                    # Намеренно пусто
                }
            }
        }
        with pytest.raises(ValueError, match="Не удалось определить стартовые URL"):
            build_plan(spec_data, config_overrides={})


# ---------------------------------------------------------------------------
# Schema Validation Edge Cases
# ---------------------------------------------------------------------------


class TestSchemaValidationEdgeCases:
    def test_additional_properties_allowed_at_root(
        self, specs_dir, schema_file, valid_spec_content
    ):
        """
        Корневой уровень schema.json имеет additionalProperties: true.
        Пользовательские поля (например, 'notes') должны быть разрешены.
        """
        valid_spec_content["notes"] = "Мои заметки о парсере"
        valid_spec_content["author"] = "Research Team"

        spec_path = specs_dir / "extra_fields.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        # Не должно падать на валидации
        data = load_spec("extra_fields", specs_dir)
        assert data["notes"] == "Мои заметки о парсере"

    def test_field_rule_as_string(self, specs_dir, schema_file, valid_spec_content):
        """
        Поля в YAML могут быть заданы как простая строка (CSS-селектор).
        Это более краткий формат.
        """
        valid_spec_content["crawler"]["list"]["fields"]["text"] = ".simple-string-selector"

        spec_path = specs_dir / "string_field.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        data = load_spec("string_field", specs_dir)
        plan = build_plan(data, config_overrides={})

        assert plan.fields["text"].selector == ".simple-string-selector"
        assert plan.fields["text"].attr is None

    def test_flow_invalid_value(self, specs_dir, schema_file, valid_spec_content):
        """
        Поле flow принимает только значения из enum.
        'wrong_step' должно провалить валидацию.
        """
        valid_spec_content["flow"] = ["list", "wrong_step"]

        spec_path = specs_dir / "bad_flow.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        with pytest.raises(SpecError, match="Ошибка конфигурации"):
            load_spec("bad_flow", specs_dir)

    def test_rate_limits_invalid_type(self, specs_dir, schema_file, valid_spec_content):
        """
        crawler.limits.max_pages должен быть целым числом (minimum: 1).
        Строка вместо числа должна провалить валидацию.
        """
        valid_spec_content["crawler"]["limits"] = {"max_pages": "ten"}

        spec_path = specs_dir / "bad_rate.yaml"
        spec_path.write_text(yaml.dump(valid_spec_content, allow_unicode=True), encoding="utf-8")

        with pytest.raises(SpecError, match="Ошибка конфигурации"):
            load_spec("bad_rate", specs_dir)
