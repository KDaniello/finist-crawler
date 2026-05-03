"""
Интеграционный тест подсистемы троттлинга и ретраев.
Связка: LightExecutor + TokenBucket + HTTP 429.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from engine.executors.light import LightExecutor
from engine.parsing_rules import CrawlerPlan, FieldRule
from engine.rate_limiter import DomainConfig


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
@patch("engine.executors.light.LightExecutor._warmup", new_callable=AsyncMock)
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_executor_respects_429_and_retries(
    mock_sleep, mock_warmup, mock_domain_config_cls, httpserver: HTTPServer
):
    """
    СЦЕНАРИЙ: Локальный сервер возвращает 429 на первый запрос, и 200 на второй.
    ОЖИДАНИЕ: LightExecutor поймает 429, сделает ретрай.
    """
    mock_domain_config_cls.return_value = DomainConfig(
        requests_per_second=100.0,
        burst_size=1,
        min_delay_ms=1.0,
        max_delay_ms=1.0,
        adaptive=True,
    )

    request_count = 0

    def rate_limit_handler(request: Request) -> Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return Response("Too Many Requests", status=429)
        return Response('{"id": 1, "text": "Success"}', status=200, content_type="application/json")

    httpserver.expect_request("/api/data").respond_with_handler(rate_limit_handler)
    url = httpserver.url_for("/api/data")

    plan = CrawlerPlan(
        start_urls=[url],
        start_phase="list",
        item_selector="@",
        extraction_mode="json",
        request_headers={},
        fields={"text": FieldRule(selector="text")},
        render_strategy="static",
    )

    records = []

    async with LightExecutor() as light:
        total, stats = await light.execute(plan, save_cb=lambda r: records.extend(r))

    assert request_count == 2
    assert total == 1
    assert records[0]["text"] == "Success"
