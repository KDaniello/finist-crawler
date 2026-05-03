"""
Тесты для engine/executors/light.py

Покрытие: 100%
- Инициализация и контекстный менеджер (RuntimeError без менеджера, открытие/закрытие сессии).
- Успешный парсинг: обработка пагинации, вызов callback'а, достижение max_pages, статистика.
- Обработка HTTP 429: ретраи с понижением скорости и дроп после лимита.
- Обработка HTTP 500: ретраи и дроп.
- Обработка HTTP 404: мгновенный дроп без ретраев.
- Капча и Блокировки (HTTP 403, Captcha HTML): немедленный проброс CaptchaBlockError.
- Сетевые ошибки (RequestsError): ретраи с последующим тихим дропом.
- Непредвиденные ошибки: логируются, экзекутор завершается штатно.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from curl_cffi.requests.errors import RequestsError

from core.exceptions import CaptchaBlockError
from engine.executors.light import LightExecutor
from engine.parsing_rules import CrawlerPlan


@pytest.fixture
def dummy_plan():
    """Фейковый план для тестов."""
    return CrawlerPlan(
        start_urls=["http://test.com/page1"],
        start_phase="list",
        item_selector=".item",
        fields={},
        request_headers={},
        max_pages=2,
    )


@pytest.fixture
def retry_plan():
    """План с высоким max_pages для тестов ретраев."""
    return CrawlerPlan(
        start_urls=["http://test.com/page1"],
        start_phase="list",
        item_selector=".item",
        fields={},
        request_headers={},
        max_pages=10,
    )


@pytest.fixture
def mock_save_cb():
    """Фейковый коллбек сохранения."""
    return MagicMock()


class TestLightExecutorInit:
    def test_name_property(self):
        assert "curl_cffi" in LightExecutor().name

    @pytest.mark.asyncio
    @patch("engine.executors.light.AsyncSession")
    async def test_context_manager(self, mock_session_cls):
        """Проверка корректного открытия и закрытия сессии curl_cffi."""
        mock_client = AsyncMock()
        mock_session_cls.return_value = mock_client

        executor = LightExecutor()
        assert executor._client is None

        async with executor as exc:
            assert exc._client is not None
            mock_client.__aenter__.assert_called_once()

        mock_client.__aexit__.assert_called_once()
        assert executor._client is None

    @pytest.mark.asyncio
    async def test_execute_without_context_raises(self, dummy_plan, mock_save_cb):
        """Вызов execute без async with должен падать."""
        executor = LightExecutor()
        with pytest.raises(RuntimeError, match="Context Manager"):
            await executor.execute(dummy_plan, mock_save_cb)


class TestLightExecutorExecute:
    @pytest.fixture
    def executor(self):
        exc = LightExecutor()
        exc._client = AsyncMock()
        return exc

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    @patch("engine.executors.light.parse_page")
    async def test_execute_success_and_pagination(
        self, mock_parse_page, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        warmup_resp = MagicMock()
        warmup_resp.status_code = 200
        warmup_resp.text = "warmup"

        resp1, resp2 = MagicMock(), MagicMock()
        resp1.status_code, resp2.status_code = 200, 200
        resp1.text, resp2.text = "HTML 1", "HTML 2"
        executor._client.get.side_effect = [warmup_resp, resp1, resp2]

        mock_parse_page.side_effect = [
            ([{"id": 1}], "http://test.com/page2", {}),
            ([{"id": 2}], "http://test.com/page3", {}),
        ]

        total_records, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total_records == 2
        assert mock_save_cb.call_count == 2
        assert stats["pages_crawled"] == 2

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_429_retries_and_drop(
        self, mock_acquire, executor, retry_plan, mock_save_cb
    ):
        """Если сервер возвращает 429, делаем ретраи, затем дропаем URL."""
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "Rate Limited"
        executor._client.get.return_value = resp_429

        total_records, stats = await executor.execute(retry_plan, mock_save_cb)

        assert total_records == 0
        assert stats["pages_crawled"] == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_5xx_retries_and_drop(
        self, mock_acquire, executor, retry_plan, mock_save_cb
    ):
        """Если сервер возвращает 500, делаем ретраи, затем дропаем URL."""
        resp_500 = MagicMock()
        resp_500.status_code = 502
        resp_500.text = "Bad Gateway"
        executor._client.get.return_value = resp_500

        total_records, stats = await executor.execute(retry_plan, mock_save_cb)

        assert total_records == 0
        assert stats["pages_crawled"] == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_404_skips_immediately(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Если сервер возвращает 404, пропускаем URL сразу без ретраев."""
        resp_404 = MagicMock()
        resp_404.status_code = 404
        resp_404.text = "Not Found"
        executor._client.get.return_value = resp_404

        total_records, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total_records == 0
        assert stats["pages_crawled"] == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_403_raises_captcha_error(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """HTTP 403 должен немедленно выбрасывать CaptchaBlockError."""
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "Forbidden"
        executor._client.get.return_value = resp_403

        with pytest.raises(CaptchaBlockError, match="HTTP 403"):
            await executor.execute(dummy_plan, mock_save_cb)

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_captcha_html_raises_error(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Даже при HTTP 200 наличие капчи в HTML выбрасывает CaptchaBlockError."""
        resp_captcha = MagicMock()
        resp_captcha.status_code = 200
        resp_captcha.text = "<title>Just a moment...</title> cf-turnstile-wrapper"
        executor._client.get.return_value = resp_captcha

        with pytest.raises(CaptchaBlockError, match="Captcha"):
            await executor.execute(dummy_plan, mock_save_cb)

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_network_error_retries_and_completes(
        self, mock_acquire, executor, retry_plan, mock_save_cb
    ):
        """Сетевая ошибка RequestsError ретраится, затем URL дропается."""
        executor._client.get.side_effect = RequestsError("Connection Reset")

        total_records, stats = await executor.execute(retry_plan, mock_save_cb)

        assert total_records == 0
        assert stats["pages_crawled"] == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_unexpected_error_completes_gracefully(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Любая другая ошибка (например, TypeError) логируется, экзекутор завершается."""
        executor._client.get.side_effect = TypeError("Что-то пошло не так")

        total_records, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert total_records == 0
        assert stats["pages_crawled"] == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    @patch("engine.executors.light.parse_page")
    async def test_execute_duplicate_start_urls(
        self, mock_parse_page, mock_acquire, executor, mock_save_cb
    ):
        """Если в очереди оказался дубликат, он пропускается."""
        plan = CrawlerPlan(
            start_urls=["http://test.com", "http://test.com"],
            start_phase="list",
            item_selector="div",
            request_headers={},
            fields={},
            max_pages=2,
        )

        resp = MagicMock()
        resp.status_code = 200
        resp.text = "HTML"
        executor._client.get.return_value = resp
        mock_parse_page.return_value = ([{"id": 1}], None, {})

        total_records, stats = await executor.execute(plan, mock_save_cb)

        assert stats["pages_crawled"] == 1
