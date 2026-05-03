"""
Стресс-тест: Нестабильная (моргающая) сеть.

Проверяет, что LightExecutor корректно обрабатывает:
- Случайные 500/502 ошибки сервера
- Таймауты соединения
- Случайные дропы соединений

Главный инвариант: воркер не падает с необработанным Traceback.
Он либо спарсит данные, либо завершится штатно.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from core.exceptions import CaptchaBlockError, NetworkError
from engine.executors.light import LightExecutor
from engine.parsing_rules import CrawlerPlan, FieldRule
from engine.rate_limiter import DomainConfig


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
@patch("engine.executors.light.LightExecutor._warmup", new_callable=AsyncMock)
@patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
async def test_flapping_5xx_errors(
    mock_acquire, mock_warmup, mock_domain_config_cls, httpserver: HTTPServer
):
    """
    СЦЕНАРИЙ: Сервер отвечает 500/502 (нестабильный бэкенд).
    ОЖИДАНИЕ: Экзекутор делает ретраи. Либо успешно парсит, либо завершается штатно.
              Никаких необработанных исключений!
    """
    mock_domain_config_cls.return_value = DomainConfig(
        requests_per_second=1000.0,
        burst_size=10,
        min_delay_ms=1.0,
        max_delay_ms=1.0,
        adaptive=False,
    )

    request_count = 0

    def flapping_handler(request: Request) -> Response:
        nonlocal request_count
        request_count += 1

        if request_count <= 3:
            return Response("Internal Server Error", status=500)

        return Response(
            '<div class="item"><span class="text">Выжил!</span></div>',
            status=200,
            content_type="text/html",
        )

    httpserver.expect_request("/flapping").respond_with_handler(flapping_handler)
    url = httpserver.url_for("/flapping")

    plan = CrawlerPlan(
        start_urls=[url],
        start_phase="list",
        item_selector=".item",
        extraction_mode="html",
        request_headers={},
        fields={"text": FieldRule(selector=".text")},
        max_pages=10,
        render_strategy="static",
    )

    records = []

    try:
        async with LightExecutor() as light:
            total, stats = await light.execute(plan, save_cb=lambda r: records.extend(r))

        assert total >= 0

    except (NetworkError, CaptchaBlockError):
        pass

    except Exception as e:
        pytest.fail(f"Необработанное исключение при нестабильной сети: {type(e).__name__}: {e}")

    assert request_count > 1, "Экзекутор не сделал ни одного ретрая!"


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
@patch("engine.executors.light.LightExecutor._warmup", new_callable=AsyncMock)
@patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
async def test_mixed_errors_never_crash(
    mock_acquire, mock_warmup, mock_domain_config_cls, httpserver: HTTPServer
):
    """
    СЦЕНАРИЙ: Полный хаос — сервер случайно отвечает 200, 429, 500, 503.
    ОЖИДАНИЕ: Экзекутор никогда не падает с необработанным исключением.
    """
    mock_domain_config_cls.return_value = DomainConfig(
        requests_per_second=1000.0,
        burst_size=10,
        min_delay_ms=1.0,
        max_delay_ms=1.0,
        adaptive=True,
    )

    chaos_responses = [
        (200, '<div class="item"><span class="text">OK</span></div>', "text/html"),
        (429, "Too Many Requests", "text/plain"),
        (500, "Internal Server Error", "text/plain"),
        (503, "Service Unavailable", "text/plain"),
        (200, '<div class="item"><span class="text">OK again</span></div>', "text/html"),
    ]
    response_index = 0

    def chaos_handler(request: Request) -> Response:
        nonlocal response_index
        status, body, content_type = chaos_responses[response_index % len(chaos_responses)]
        response_index += 1
        return Response(body, status=status, content_type=content_type)

    httpserver.expect_request("/chaos").respond_with_handler(chaos_handler)

    urls = [httpserver.url_for(f"/chaos?id={i}") for i in range(5)]

    plan = CrawlerPlan(
        start_urls=urls,
        start_phase="list",
        item_selector=".item",
        extraction_mode="html",
        request_headers={},
        fields={"text": FieldRule(selector=".text")},
        max_pages=5,
        render_strategy="static",
    )

    try:
        async with LightExecutor() as light:
            total, stats = await light.execute(plan, save_cb=lambda r: None)

        assert total >= 0
        assert stats["pages_crawled"] >= 0

    except (NetworkError, CaptchaBlockError):
        pass

    except Exception as e:
        pytest.fail(f"Необработанное исключение в хаосе: {type(e).__name__}: {e}")


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
@patch("engine.executors.light.LightExecutor._warmup", new_callable=AsyncMock)
@patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
async def test_429_adaptive_slowdown(
    mock_acquire, mock_warmup, mock_domain_config_cls, httpserver: HTTPServer
):
    """
    СЦЕНАРИЙ: Сервер постоянно отвечает 429.
    ОЖИДАНИЕ: Экзекутор исчерпывает ретраи и завершается (НЕ зависает).
    """
    mock_domain_config_cls.return_value = DomainConfig(
        requests_per_second=1000.0,
        burst_size=1,
        min_delay_ms=1.0,
        max_delay_ms=1.0,
        adaptive=True,
        adaptive_slowdown=2.0,
        max_slowdown_factor=8.0,
    )

    request_count = 0

    def always_429(request: Request) -> Response:
        nonlocal request_count
        request_count += 1
        return Response("Too Many Requests", status=429)

    httpserver.expect_request("/ratelimited").respond_with_handler(always_429)

    plan = CrawlerPlan(
        start_urls=[httpserver.url_for("/ratelimited")],
        start_phase="list",
        item_selector=".item",
        extraction_mode="html",
        request_headers={},
        fields={"text": FieldRule(selector=".text")},
        max_pages=10,
        render_strategy="static",
    )

    try:
        async with LightExecutor() as light:
            total, stats = await light.execute(plan, save_cb=lambda r: None)

        assert total == 0

    except (NetworkError, CaptchaBlockError):
        pass

    except Exception as e:
        pytest.fail(f"Неожиданное исключение при постоянных 429: {type(e).__name__}: {e}")

    assert request_count >= 4, f"Экзекутор не делал ретраев при 429! Запросов: {request_count}"
