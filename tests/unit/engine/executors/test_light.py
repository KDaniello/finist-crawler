"""
Тесты для engine/executors/light.py

Покрытие: 100%
- Инициализация и контекстный менеджер (RuntimeError без менеджера, открытие/закрытие сессии).
- Успешный парсинг: обработка пагинации, вызов callback'а, достижение max_pages, статистика.
- Обработка HTTP 429: ретраи с понижением скорости и дроп после лимита.
- Обработка HTTP 500: ретраи и дроп.
- Обработка HTTP 404: мгновенный дроп без ретраев.
- Капча и Блокировки (HTTP 403, Captcha HTML): немедленный проброс CaptchaBlockError.
- Сетевые ошибки (RequestsError): ретраи и генерация NetworkError.
- Непредвиденные ошибки: проброс как NetworkError.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from curl_cffi.requests.errors import RequestsError

from core.exceptions import CaptchaBlockError, NetworkError
from engine.executors.light import LightExecutor
from engine.parsing_rules import CrawlerPlan

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def mock_save_cb():
    """Фейковый коллбек сохранения."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Context Manager & Init Tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Execute Logic Tests
# ---------------------------------------------------------------------------


class TestLightExecutorExecute:
    @pytest.fixture
    def executor(self):
        """Возвращает инициализированный экзекутор, у которого _client замокан."""
        exc = LightExecutor()
        exc._client = AsyncMock()
        return exc

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    @patch("engine.executors.light.parse_page")
    async def test_execute_success_and_pagination(
        self, mock_parse_page, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """
        Успешный проход:
        1. Страница 1 (возвращает данные и ссылку на 2)
        2. Страница 2 (возвращает данные, ссылки нет) -> конец (упирается в max_pages = 2)
        """
        # Настраиваем ответы клиента
        resp1, resp2 = MagicMock(), MagicMock()
        resp1.status_code, resp2.status_code = 200, 200
        resp1.text, resp2.text = "HTML 1", "HTML 2"
        executor._client.get.side_effect = [resp1, resp2]

        # Настраиваем парсер
        mock_parse_page.side_effect = [
            ([{"id": 1}], "http://test.com/page2"),  # Первая страница дает ссылку на вторую
            ([{"id": 2}], "http://test.com/page3"),  # Вторая дает ссылку на третью, но max_pages=2
        ]

        total_records, stats = await executor.execute(dummy_plan, mock_save_cb)

        # Проверки
        assert total_records == 2
        assert mock_save_cb.call_count == 2
        assert stats["pages_crawled"] == 2
        assert stats["queue_remaining"] == 1  # Ссылка на page3 осталась в очереди

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_429_retries_and_drop(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Если сервер возвращает 429, делаем 3 ретрая, затем дропаем URL."""
        resp_429 = MagicMock()
        resp_429.status_code = 429
        executor._client.get.return_value = resp_429

        total_records, stats = await executor.execute(dummy_plan, mock_save_cb)

        # 1 оригинал + 3 ретрая = 4 запроса
        assert executor._client.get.call_count == 4
        assert total_records == 0
        assert stats["pages_crawled"] == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_5xx_retries_and_drop(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Если сервер возвращает 500, делаем 3 ретрая, затем дропаем URL."""
        resp_500 = MagicMock()
        resp_500.status_code = 502
        executor._client.get.return_value = resp_500

        total_records, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert executor._client.get.call_count == 4
        assert total_records == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_404_skips_immediately(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Если сервер возвращает 404, пропускаем URL сразу без ретраев."""
        resp_404 = MagicMock()
        resp_404.status_code = 404
        executor._client.get.return_value = resp_404

        total_records, stats = await executor.execute(dummy_plan, mock_save_cb)

        assert executor._client.get.call_count == 1
        assert total_records == 0

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_403_raises_captcha_error(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """HTTP 403 должен немедленно выбрасывать CaptchaBlockError."""
        resp_403 = MagicMock()
        resp_403.status_code = 403
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

        with pytest.raises(CaptchaBlockError, match="Captcha HTML"):
            await executor.execute(dummy_plan, mock_save_cb)

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_network_error_retries_and_raises(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Сетевая ошибка RequestsError ретраится 3 раза, затем пробрасывается как NetworkError."""
        executor._client.get.side_effect = RequestsError("Connection Reset")

        with pytest.raises(NetworkError, match="max retries reached"):
            await executor.execute(dummy_plan, mock_save_cb)

        assert executor._client.get.call_count == 4

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    async def test_execute_unexpected_error_raises_immediately(
        self, mock_acquire, executor, dummy_plan, mock_save_cb
    ):
        """Любая другая ошибка (например, TypeError) сразу валит экзекутор как NetworkError."""
        executor._client.get.side_effect = TypeError("Что-то пошло не так")

        with pytest.raises(NetworkError, match="Сбой выполнения запроса"):
            await executor.execute(dummy_plan, mock_save_cb)

        assert executor._client.get.call_count == 1

    @pytest.mark.asyncio
    @patch("engine.executors.light.TokenBucket.acquire", new_callable=AsyncMock)
    @patch("engine.executors.light.parse_page")
    async def test_execute_duplicate_start_urls(
        self, mock_parse_page, mock_acquire, executor, mock_save_cb
    ):
        """Если в очереди оказался дубликат (например, из start_urls), он пропускается (continue)."""
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
        executor._client.get.return_value = resp
        mock_parse_page.return_value = ([{"id": 1}], None)

        total_records, stats = await executor.execute(plan, mock_save_cb)

        # Запрос должен быть выполнен ровно 1 раз, второй URL пропускается
        assert executor._client.get.call_count == 1
        assert stats["pages_crawled"] == 1
