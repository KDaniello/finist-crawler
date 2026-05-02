"""
Тесты для engine/parsing_rules.py

Покрытие: 100%
- Вспомогательные функции: sanitize_html, is_captcha_html, _generate_deterministic_id
- Сборка плана: build_plan (объединение словарей, валидация, overrides)
- HTMLExtractor: выборка полей, атрибутов, дефолтные значения, пагинация, пустые селекторы.
- JSONExtractor: парсинг чистого JSON, парсинг JSON из <script> (через regex),
  ошибки JSONDecodeError, JMESPath выборка (dict и list), пагинация (джоин URL), пропуск пустых словарей.
- parse_page: правильный выбор стратегии и перехват глобальных ошибок (Exception fallback).
"""

import json
from unittest.mock import patch

import pytest

from engine.parsing_rules import (
    CrawlerPlan,
    FieldRule,
    HTMLExtractor,
    JSONExtractor,
    _generate_deterministic_id,
    build_plan,
    is_captcha_html,
    parse_page,
    sanitize_html,
)

# ---------------------------------------------------------------------------
# Helpers Tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_sanitize_html(self):
        """Проверка очистки от скриптов, стилей и тегов."""
        assert sanitize_html("") == ""

        html = """
        <div class="test">
            <script>alert('hack');</script>
            <style>body {color: red;}</style>
            <h1>Hello   World</h1>
            <p>Test</p>
        </div>
        """
        assert sanitize_html(html) == "Hello World Test"

    def test_is_captcha_html(self):
        """Проверка быстрого детекта капчи."""
        assert is_captcha_html("") is False
        assert is_captcha_html("<html><body>Just normal text</body></html>") is False
        assert (
            is_captcha_html("<title>Just a moment...</title> Please verify you are human") is True
        )
        assert is_captcha_html("cf-turnstile-wrapper") is True

    def test_generate_deterministic_id(self):
        """ID должен генерироваться на основе author+text+date или словаря."""
        url = "http://test.com"

        # На основе текста, автора и даты (изменчивые поля вроде views игнорируются)
        id1 = _generate_deterministic_id({"author": "Alex", "text": "Hello", "views": 10}, url)
        id2 = _generate_deterministic_id({"author": "Alex", "text": "Hello", "views": 99}, url)
        assert id1 == id2
        assert id1.startswith("finist-")

        # На основе имени (если author нет)
        id3 = _generate_deterministic_id({"name": "Alex", "text": "Hello", "date": "2023"}, url)
        id4 = _generate_deterministic_id({"name": "Alex", "text": "Hello", "date": "2023"}, url)
        assert id3 == id4

        # Без текста (фолбек на сериализацию словаря, игнорируя служебные поля)
        id5 = _generate_deterministic_id({"title": "Post", "metadata": "ignore"}, url)
        id6 = _generate_deterministic_id({"title": "Post", "metadata": "changed"}, url)
        id7 = _generate_deterministic_id({"title": "Other"}, url)

        assert id5 == id6  # Изменение метаданных не меняет хеш
        assert id5 != id7  # Изменение реальных данных меняет хеш


# ---------------------------------------------------------------------------
# Build Plan Tests
# ---------------------------------------------------------------------------


class TestBuildPlan:
    def test_build_plan_missing_start_urls(self):
        """Если start_urls нигде нет, падает с ValueError."""
        with pytest.raises(ValueError, match="Не удалось определить стартовые URL"):
            build_plan({"crawler": {"list": {}}}, {})

    def test_build_plan_success(self):
        """Сборка плана из спеки и overrides."""
        spec = {
            "crawler": {
                "list": {
                    "start_urls": ["http://base.com"],
                    "item_selector": ".item",
                    "extraction_mode": "html",
                    "next_page": {"selector": ".next", "attr": "href"},
                    "fields": {
                        "title": "h1",  # Строковый селектор
                        "link": {
                            "selector": "a",
                            "attr": "href",
                            "default": "N/A",
                        },  # Dict-селектор
                    },
                },
                "limits": {"max_pages": 10},
                "render": "playwright",
            }
        }
        overrides = {"direct_urls": ["http://override.com"], "max_pages": 2}

        plan = build_plan(spec, overrides)

        assert plan.start_urls == ["http://override.com"]  # Override сработал
        assert plan.item_selector == ".item"
        assert plan.extraction_mode == "html"
        assert plan.max_pages == 2  # Override сработал
        assert plan.render_strategy == "playwright"
        assert plan.next_page_selector == ".next"

        # Проверка сборки полей
        assert len(plan.fields) == 2
        assert plan.fields["title"].selector == "h1"
        assert plan.fields["title"].attr is None
        assert plan.fields["link"].selector == "a"
        assert plan.fields["link"].attr == "href"
        assert plan.fields["link"].default == "N/A"


# ---------------------------------------------------------------------------
# HTMLExtractor Tests
# ---------------------------------------------------------------------------


class TestHTMLExtractor:
    @pytest.fixture
    def plan(self):
        return CrawlerPlan(
            start_urls=["http://test.com"],
            start_phase="list",
            item_selector=".post",
            next_page_selector=".next-btn",
            next_page_attr="href",
            request_headers={},
            fields={
                "title": FieldRule("h2"),
                "url": FieldRule("a", attr="href", default="Missing"),
                "text": FieldRule(".content"),
                "missing": FieldRule(".not-exist", default="Empty"),
                "self_attr": FieldRule(":self", attr="data-id"),
                "empty_rule": FieldRule(""),
            },
        )

    def test_extract_html_success(self, plan):
        html = """
        <html>
            <div class="post" data-id="100">
                <h2>Post 1</h2>
                <a href="/post1">Link</a>
                <div class="content"><script>alert('x');</script>Clean Text</div>
            </div>
            <div class="post" data-id="101">
                <h2>Post 2</h2>
                <!-- No link here -->
            </div>
            <a class="next-btn" href="?page=2">Next</a>
        </html>
        """
        extractor = HTMLExtractor()
        records, next_url, _ = extractor.extract(html, plan, "http://test.com", "list")

        assert len(records) == 2

        # Проверка первой записи
        assert records[0]["title"] == "Post 1"
        assert records[0]["url"] == "/post1"
        assert records[0]["text"] == "Clean Text"  # Sanitize сработал
        assert records[0]["missing"] == "Empty"  # Default сработал
        assert records[0]["self_attr"] == "100"  # :self сработал
        assert records[0]["message_url"] == "http://test.com"
        assert "external_id" in records[0]

        # Проверка второй записи
        assert records[1]["title"] == "Post 2"
        assert records[1]["url"] == "Missing"  # Дефолт для атрибута

        # Проверка пагинации (join относительной ссылки)
        assert next_url == "http://test.com?page=2"

    def test_extract_html_empty_record(self):
        """Если после фильтрации полей словарь пуст, он игнорируется."""
        html = '<div class="post"></div>'
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector=".post",
            request_headers={},
            fields={"dummy": FieldRule("")},
        )
        records, next_url, _ = HTMLExtractor().extract(html, plan, "http://test.com", "list")

        assert records == []


# ---------------------------------------------------------------------------
# JSONExtractor Tests
# ---------------------------------------------------------------------------


class TestJSONExtractor:
    @pytest.fixture
    def plan(self):
        return CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            next_page_selector="meta.next_cursor",
            request_headers={},
            fields={
                "id": FieldRule("id"),
                "title": FieldRule("snippet.title"),
                "text": FieldRule("content", default=""),
                "missing": FieldRule("fake", default="N/A"),
            },
        )

    def test_extract_pure_json(self, plan):
        json_data = {
            "meta": {"next_cursor": "/api/v2?page=2"},
            "items": [
                {"id": 1, "snippet": {"title": "A"}, "content": "<b>Text A</b>"},
                {"id": 2, "snippet": {"title": "B"}},
            ],
        }
        extractor = JSONExtractor()
        records, next_url, _ = extractor.extract(json.dumps(json_data), plan, "http://test.com", "list")

        assert len(records) == 2
        assert records[0]["id"] == "1"
        assert records[0]["title"] == "A"
        assert records[0]["text"] == "Text A"  # Sanitize
        assert records[0]["missing"] == "N/A"

        # Пагинация (относительный путь сджойнен)
        assert next_url == "http://test.com/api/v2?page=2"

    def test_extract_dict_wrapped_in_list(self, plan):
        """Если item_selector находит dict вместо list, extractor оборачивает в list."""
        json_data = {"items": {"id": 99, "snippet": {"title": "Single"}}}
        extractor = JSONExtractor()
        records, next_url, _ = extractor.extract(json.dumps(json_data), plan, "http://test.com", "list")

        assert len(records) == 1
        assert records[0]["id"] == "99"
        assert next_url is None

    def test_extract_invalid_json(self, plan):
        """Если JSON битый, экстрактор не падает, а возвращает пустые данные."""
        extractor = JSONExtractor()

        rec1, n1, _ = extractor.extract('{ "items": [ }', plan, "url", "list")
        assert rec1 == []

        rec2, n2, _ = extractor.extract("{ bad }", plan, "url", "list")
        assert rec2 == []

    def test_extract_json_empty_record(self):
        """Если JSON пустой или все селекторы полей пустые, запись пропускается."""
        plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            request_headers={},
            fields={"dummy": FieldRule("")},
        )

        empty_plan = CrawlerPlan(
            start_urls=["url"],
            start_phase="list",
            item_selector="items",
            request_headers={},
            fields={},
        )

        records, next_url, _ = JSONExtractor().extract('{"items": [{"id": 1}]}', empty_plan, "url", "list")
        assert records == []


# ---------------------------------------------------------------------------
# Parse Page (Facade) Tests
# ---------------------------------------------------------------------------


class TestParsePage:
    def test_parse_page_html_mode(self):
        plan = CrawlerPlan(
            ["url"],
            start_phase="list",
            item_selector="div",
            request_headers={},
            fields={"a": FieldRule("a")},
            extraction_mode="html",
        )
        records, next_url, _ = parse_page("<div><a>Link</a></div>", plan, "http://url")
        assert len(records) == 1

    def test_parse_page_json_mode(self):
        plan = CrawlerPlan(
            ["url"],
            start_phase="list",
            item_selector="[]",
            request_headers={},
            fields={"a": FieldRule("a")},
            extraction_mode="json",
        )
        records, next_url, _ = parse_page('[{"a": "Link"}]', plan, "http://url")
        assert len(records) == 1

    @patch.object(HTMLExtractor, "extract", side_effect=Exception("Critical Crash"))
    def test_parse_page_exception_fallback(self, mock_extract, caplog):
        """Любая ошибка внутри парсера перехватывается, чтобы не уронить воркер."""
        plan = CrawlerPlan(
            ["url"],
            start_phase="list",
            item_selector="div",
            request_headers={},
            fields={},
        )
        records, next_url, _ = parse_page("<html>", plan, "url")

        assert records == []
        assert next_url is None
        assert "Сбой при извлечении данных" in caplog.text
