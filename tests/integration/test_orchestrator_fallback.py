"""
Интеграционный тест цепочки деградации (Graceful Degradation).

Проверяет логику Оркестратора: перехват 403/Captcha от локального HTTP-сервера
через LightExecutor и успешную передачу управления в StealthExecutor.
Физический запуск браузера (Playwright) заблокирован фикстурой во избежание крашей ОС.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_httpserver import HTTPServer

from core.exceptions import CaptchaBlockError
from engine.fallback_chain import FallbackOrchestrator
from engine.parsing_rules import CrawlerPlan, FieldRule


@pytest.fixture(autouse=True)
def _patch_for_speed():
    with patch("engine.executors.light.LightExecutor._warmup", new_callable=AsyncMock), \
         patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock):
        yield


@pytest.fixture(autouse=True)
def prevent_real_browser_launch(monkeypatch):
    """
    Блокируем запуск реального firefox.exe.
    Мы тестируем логику Fallback, а не движок Playwright.
    """
    mock_browser = AsyncMock()

    mock_browser.page.content.return_value = """
        <html><body>
            <div class="item"><span class="text">Stealth Данные 1</span><span class="author">Charlie</span></div>
            <div class="item"><span class="text">Stealth Данные 2</span><span class="author">Dave</span></div>
        </body></html>
    """

    monkeypatch.setattr(
        "engine.executors.stealth.ImmortalBrowser.__aenter__", AsyncMock(return_value=mock_browser)
    )
    monkeypatch.setattr("engine.executors.stealth.ImmortalBrowser.__aexit__", AsyncMock())
    monkeypatch.setattr("engine.executors.stealth.is_captcha_html", MagicMock(return_value=False))


@pytest.fixture
def plan_factory():
    def _make_plan(url: str, render_strategy: str = "auto") -> CrawlerPlan:
        return CrawlerPlan(
            start_urls=[url],
            start_phase="list",
            item_selector=".item",
            extraction_mode="html",
            request_headers={},
            fields={
                "text": FieldRule(selector=".text"),
                "author": FieldRule(selector=".author"),
            },
            max_pages=1,
            render_strategy=render_strategy,
        )

    return _make_plan


class RecordCatcher:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def __call__(self, new_records: list[dict[str, Any]]) -> None:
        self.records.extend(new_records)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_light_executor_success(
    httpserver: HTTPServer, browser_lock, plan_factory, tmp_path: Path
):
    """LightExecutor сам справляется с задачей. Браузер не вызывается."""
    httpserver.expect_request("/clean").respond_with_data(
        '<body><div class="item"><span class="author">Alice</span></div></body>',
        content_type="text/html",
    )

    plan = plan_factory(httpserver.url_for("/clean"), render_strategy="auto")
    catcher = RecordCatcher()
    orchestrator = FallbackOrchestrator(browser_lock, profiles_dir=tmp_path / "profiles")

    total_saved, stats = await orchestrator.execute_plan(plan, save_cb=catcher)

    assert total_saved == 1
    assert catcher.records[0]["author"] == "Alice"
    assert "curl_cffi" in stats.get("executor", "").lower()


@pytest.mark.asyncio
async def test_fallback_chain_triggers_stealth(
    httpserver: HTTPServer, browser_lock, plan_factory, tmp_path: Path
):
    """LightExecutor ловит HTML-капчу -> Оркестратор запускает StealthExecutor."""

    # Сервер отдает маркер Cloudflare (cf-challenge-running)
    httpserver.expect_request("/captcha").respond_with_data(
        '<div id="cf-challenge-running">Wait...</div>', content_type="text/html"
    )

    plan = plan_factory(httpserver.url_for("/captcha"), render_strategy="auto")
    catcher = RecordCatcher()
    orchestrator = FallbackOrchestrator(browser_lock, profiles_dir=tmp_path / "profiles")

    total_saved, stats = await orchestrator.execute_plan(plan, save_cb=catcher)

    # Данные должны быть из фикстуры `prevent_real_browser_launch` (Charlie и Dave)
    assert total_saved == 2
    assert catcher.records[0]["author"] == "Charlie"
    assert "camoufox" in stats.get("executor", "").lower()


@pytest.mark.asyncio
async def test_static_strategy_fails_on_captcha(
    httpserver: HTTPServer, browser_lock, plan_factory, tmp_path: Path
):
    """Стратегия 'static' запрещает запуск браузера. Капча вызывает ошибку."""
    httpserver.expect_request("/captcha_static").respond_with_data(
        '<div id="cf-challenge-running">Wait...</div>', content_type="text/html"
    )

    plan = plan_factory(httpserver.url_for("/captcha_static"), render_strategy="static")
    catcher = RecordCatcher()
    orchestrator = FallbackOrchestrator(
        browser_lock, profiles_dir=tmp_path / "profiles", render_strategy="static"
    )

    with pytest.raises(CaptchaBlockError):
        await orchestrator.execute_plan(plan, save_cb=catcher)


@pytest.mark.asyncio
async def test_browser_strategy_direct(
    httpserver: HTTPServer, browser_lock, plan_factory, tmp_path: Path
):
    """Стратегия 'browser' сразу переходит к StealthExecutor."""
    httpserver.expect_request("/clean_browser").respond_with_data("ok")

    plan = plan_factory(httpserver.url_for("/clean_browser"), render_strategy="browser")
    catcher = RecordCatcher()
    orchestrator = FallbackOrchestrator(
        browser_lock, profiles_dir=tmp_path / "profiles", render_strategy="browser"
    )

    total_saved, stats = await orchestrator.execute_plan(plan, save_cb=catcher)

    assert total_saved == 2
    assert "camoufox" in stats.get("executor", "").lower()
