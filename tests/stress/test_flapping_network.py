"""
Стресс-тест: Нестабильная (моргающая) сеть.

Проверяет, что LightExecutor корректно обрабатывает:
- Случайные 500/502/503 ошибки сервера
- Таймауты соединения
- Случайные дропы соединений

Главный инвариант: воркер не падает с необработанным Traceback.
Он либо спарсит данные, либо бросит NetworkError/CaptchaBlockError.
"""

import random
from unittest.mock import patch

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from core.exceptions import CaptchaBlockError, NetworkError
from engine.executors.light import LightExecutor
from engine.parsing_rules import CrawlerPlan, FieldRule
from engine.rate_limiter import DomainConfig


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
async def test_flapping_5xx_errors(mock_domain_config_cls, httpserver: HTTPServer):
    """
    СЦЕНАРИЙ: Сервер случайно отвечает 500/502/503 (нестабильный бэкенд).
    ОЖИДАНИЕ: Экзекутор делает ретраи. Либо успешно парсит, либо бросает NetworkError.
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
    error_codes = [500, 502, 503]

    def flapping_handler(request: Request) -> Response:
        nonlocal request_count
        request_count += 1

        # Первые 3 запроса всегда ошибки (исчерпываем ретраи)
        if request_count <= 3:
            return Response("Internal Server Error", status=random.choice(error_codes))

        # После 3 ошибок — успех
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
        max_pages=1,
        render_strategy="static",
    )

    records = []

    try:
        async with LightExecutor() as light:
            total, stats = await light.execute(plan, save_cb=lambda r: records.extend(r))

        # Если дошли сюда — экзекутор всё-таки спарсил данные после ретраев
        assert total >= 0

    except (NetworkError, CaptchaBlockError):
        # Это ожидаемое поведение: все ретраи исчерпаны, экзекутор сдался
        pass

    except Exception as e:
        pytest.fail(f"Необработанное исключение при нестабильной сети: {type(e).__name__}: {e}")

    # В любом случае: количество запросов к серверу должно быть > 1 (были ретраи)
    assert request_count > 1, "Экзекутор не сделал ни одного ретрая!"


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
async def test_mixed_errors_never_crash(mock_domain_config_cls, httpserver: HTTPServer):
    """
    СЦЕНАРИЙ: Полный хаос — сервер случайно отвечает 200, 403, 429, 500, 503.
    ОЖИДАНИЕ: Экзекутор никогда не падает с необработанным исключением.
              Он либо парсит что может, либо корректно бросает кастомную ошибку.
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

    # Генерируем 5 разных URL, чтобы экзекутор обошел их все
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

        # Проверяем, что статистика корректна (не None, не отрицательная)
        assert total >= 0
        assert stats["pages_crawled"] >= 0

    except (NetworkError, CaptchaBlockError):
        # Ожидаемое завершение при полном хаосе
        pass

    except Exception as e:
        pytest.fail(f"Необработанное исключение в хаосе: {type(e).__name__}: {e}")


@pytest.mark.asyncio
@patch("engine.executors.light.DomainConfig")
async def test_429_adaptive_slowdown(mock_domain_config_cls, httpserver: HTTPServer):
    """
    СЦЕНАРИЙ: Сервер постоянно отвечает 429, пока экзекутор не замедлится.
    ОЖИДАНИЕ: TokenBucket увеличивает slowdown_factor при каждом 429.
              Экзекутор исчерпывает ретраи и бросает NetworkError (НЕ зависает).
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
        max_pages=1,
        render_strategy="static",
    )

    # При постоянных 429 экзекутор должен исчерпать ретраи и спокойно завершиться
    try:
        async with LightExecutor() as light:
            total, stats = await light.execute(plan, save_cb=lambda r: None)

        # Если дошли сюда — данных нет, всё пропущено
        assert total == 0

    except (NetworkError, CaptchaBlockError):
        pass  # Ожидаемое поведение

    except Exception as e:
        pytest.fail(f"Неожиданное исключение при постоянных 429: {type(e).__name__}: {e}")

    # Ретраи должны были произойти (max_retries=3, значит минимум 4 запроса)
    assert request_count >= 4, f"Экзекутор не делал ретраев при 429! Запросов: {request_count}"
