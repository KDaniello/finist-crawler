"""
Performance тест: Утечки памяти в легком экзекуторе (curl_cffi).
Доказывает, что парсинг большого количества страниц не раздувает ОЗУ.
"""

import gc
import os
from unittest.mock import patch

import psutil
import pytest
from pytest_httpserver import HTTPServer

from engine.executors.light import LightExecutor
from engine.parsing_rules import CrawlerPlan, FieldRule
from engine.rate_limiter import DomainConfig

# HTML-шаблон: 10 записей на страницу, каждая ~1 КБ данных
_PAGE_HTML = """
<html><body>
{items}
</body></html>
""".format(
    items="\n".join(
        f'<div class="item"><span class="id">{i}</span><span class="data">{"X" * 500}</span></div>'
        for i in range(10)
    )
)


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
async def test_light_executor_no_memory_leak(mock_domain_config_cls, httpserver: HTTPServer):
    """
    СЦЕНАРИЙ: Парсим 100 независимых URL-страниц (по 10 записей каждая = 1000 записей суммарно).
    ОЖИДАНИЕ: Рост RSS-памяти процесса не превысит 20 МБ.
              Данные не копятся в памяти — они уходят в коллбек и собираются GC.
    """
    # Убираем задержки RateLimiter для скорости
    mock_domain_config_cls.return_value = DomainConfig(
        requests_per_second=1000.0,
        burst_size=100,
        min_delay_ms=0.1,
        max_delay_ms=0.1,
        adaptive=False,
    )

    # Регистрируем один эндпоинт, который всегда отвечает одинаково
    httpserver.expect_request("/page").respond_with_data(_PAGE_HTML, content_type="text/html")
    page_url = httpserver.url_for("/page")

    # Генерируем 100 URL — один и тот же эндпоинт с разными query-параметрами
    # чтобы механизм visited не отфильтровал их как дубликаты
    start_urls = [f"{page_url}?p={i}" for i in range(100)]

    plan = CrawlerPlan(
        start_urls=start_urls,
        start_phase="list",
        item_selector=".item",
        extraction_mode="html",
        request_headers={},
        fields={
            "id": FieldRule(selector=".id"),
            "data": FieldRule(selector=".data"),
        },
        max_pages=100,
        render_strategy="static",
    )

    process = psutil.Process(os.getpid())

    # --- ПРОГРЕВ ---
    # Первый запуск инициализирует TLS, компилирует CSS-селекторы и прогревает кэши.
    # Его мы не считаем в замере.
    async with LightExecutor() as light:
        await light.execute(
            CrawlerPlan(
                start_urls=[page_url],
                start_phase="list",
                item_selector=".item",
                extraction_mode="html",
                request_headers={},
                fields={"id": FieldRule(selector=".id")},
                max_pages=1,
            ),
            save_cb=lambda x: None,
        )

    # Принудительная сборка мусора перед замером
    gc.collect()

    # --- ЗАМЕР ДО ---
    mem_before_mb = process.memory_info().rss / (1024 * 1024)

    # --- БОЕВОЙ ПРОГОН ---
    total_parsed = 0

    def save_callback(records: list) -> None:
        nonlocal total_parsed
        total_parsed += len(records)
        # Данные намеренно НЕ сохраняем в список — они должны уйти в GC

    async with LightExecutor() as light:
        total, stats = await light.execute(plan, save_cb=save_callback)

    # Принудительная сборка мусора после прогона
    gc.collect()

    # --- ЗАМЕР ПОСЛЕ ---
    mem_after_mb = process.memory_info().rss / (1024 * 1024)
    growth_mb = mem_after_mb - mem_before_mb

    # --- ПРОВЕРКИ ---
    assert total == 1000, f"Ожидали 1000 записей, получили {total}"
    assert total_parsed == 1000

    assert growth_mb < 20.0, (
        f"Утечка памяти обнаружена!\n"
        f"  Память до:   {mem_before_mb:.1f} MB\n"
        f"  Память после: {mem_after_mb:.1f} MB\n"
        f"  Рост:        {growth_mb:.1f} MB (лимит: 20 MB)"
    )

    print(
        f"\n[PERF] Память до: {mem_before_mb:.1f} MB | "
        f"после: {mem_after_mb:.1f} MB | "
        f"рост: {growth_mb:.1f} MB | "
        f"записей: {total}"
    )
