"""
Тесты для engine/rate_limiter.py

Покрытие: 100%
- DomainConfig: проверка frozen (неизменяемости).
- TokenBucket _refill: математика пополнения токенов (не превышает burst_size).
- TokenBucket _get_human_delay: генерация рандома в заданных рамках, защита от отрицательных чисел, влияние slowdown_factor.
- TokenBucket _calculate_wait_time: логика возврата 0 при наличии токенов, расчет времени ожидания.
- TokenBucket acquire (Async): создание лока на лету, ожидание токена, ожидание human_delay.
- TokenBucket sync_acquire (Sync): ожидание токена, ожидание human_delay.
- Управление адаптивностью:
  - report_rate_limited (умножение замедления, блокировка по max_slowdown).
  - report_success (плавное восстановление).
  - игнорирование, если adaptive=False.
"""

import time
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, patch

import pytest

from engine.rate_limiter import DomainConfig, TokenBucket

# ---------------------------------------------------------------------------
# DomainConfig Tests
# ---------------------------------------------------------------------------


class TestDomainConfig:
    def test_config_is_frozen(self):
        """DomainConfig должен быть frozen dataclass."""
        cfg = DomainConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.requests_per_second = 5.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TokenBucket Private Logic Tests
# ---------------------------------------------------------------------------


class TestTokenBucketLogic:
    @pytest.fixture
    def config(self):
        return DomainConfig(
            requests_per_second=2.0, burst_size=5, min_delay_ms=1000, max_delay_ms=2000
        )

    @pytest.fixture
    def bucket(self, config):
        return TokenBucket(config)

    @patch("time.monotonic")
    def test_refill_math(self, mock_time, bucket):
        """Проверка математики пополнения токенов (замороженное время)."""
        mock_time.return_value = 10.0  # Текущее время "замерло" на отметке 10.0

        # Изначально корзина полна (5 токенов)
        assert bucket._tokens == 5.0

        bucket._tokens = 0.0
        bucket._last_refill = 9.0  # Прошла ровно 1 секунда

        # Rate = 2.0. Значит за 1 сек должно добавиться ровно 2.0 токена
        bucket._refill()
        assert bucket._tokens == 2.0

        bucket._last_refill = 0.0  # Прошло 10 сек (набежало 20 токенов)
        bucket._refill()
        # Не должно превысить burst_size (5.0)
        assert bucket._tokens == 5.0

    def test_human_delay_bounds(self, bucket):
        """Задержка должна находиться в пределах [min_delay, max_delay] с учетом jitter."""
        # Без slowdown (x1.0). min = 1.0s, max = 2.0s, jitter = 20%
        # Худший случай: min - 20% = 0.8s, max + 20% = 2.4s
        delays = [bucket._get_human_delay() for _ in range(100)]
        assert all(0.8 <= d <= 2.4 for d in delays)

        # Со slowdown (x5.0). min = 5.0s, max = 10.0s
        # Худший случай: min - 20% = 4.0s, max + 20% = 12.0s
        bucket._slowdown_factor = 5.0
        delays_slow = [bucket._get_human_delay() for _ in range(100)]
        assert all(4.0 <= d <= 12.0 for d in delays_slow)

    def test_human_delay_negative_protection(self):
        """Задержка никогда не должна быть < 0.1s (защита от кривых настроек)."""
        cfg = DomainConfig(min_delay_ms=-5000, max_delay_ms=-1000)
        bucket = TokenBucket(cfg)
        assert bucket._get_human_delay() == 0.1

    @patch("time.monotonic")
    def test_calculate_wait_time_with_tokens(self, mock_time, bucket):
        """Если токены есть, возвращает 0.0 и забирает 1 токен."""
        mock_time.return_value = 10.0

        bucket._tokens = 2.0
        bucket._last_refill = 10.0  # Время не прошло

        wait_time = bucket._calculate_wait_time()
        assert wait_time == 0.0
        assert bucket._tokens == 1.0

    @patch("time.monotonic")
    def test_calculate_wait_time_no_tokens(self, mock_time, bucket):
        """Если токенов нет, вычисляет время до следующего токена."""
        mock_time.return_value = 10.0

        bucket._tokens = 0.0
        bucket._last_refill = 10.0  # Время не прошло

        # Rate = 2.0/s. Чтобы получить 1 токен нужно 0.5s
        wait_time = bucket._calculate_wait_time()
        assert wait_time == 0.5


# ---------------------------------------------------------------------------
# TokenBucket Async/Sync API Tests
# ---------------------------------------------------------------------------


class TestTokenBucketAPI:
    @pytest.fixture
    def bucket(self):
        cfg = DomainConfig(requests_per_second=1.0, burst_size=1)
        return TokenBucket(cfg)

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_acquire_async(self, mock_sleep, bucket):
        """Асинхронный вызов создает лок и спит 2 раза (ждем токен + human delay)."""
        bucket._tokens = 0.0
        bucket._last_refill = time.monotonic()

        await bucket.acquire()

        assert bucket._async_lock is not None
        assert mock_sleep.call_count == 2

        # Первый sleep - ожидание 1 токена (rate=1.0 -> wait 1.0s)
        wait_call = mock_sleep.call_args_list[0].args[0]
        assert round(wait_call, 1) == 1.0

        # Второй sleep - human delay
        delay_call = mock_sleep.call_args_list[1].args[0]
        assert delay_call > 0

    @patch("time.sleep")
    def test_acquire_sync(self, mock_sleep, bucket):
        """Синхронный вызов спит 2 раза через time.sleep."""
        bucket._tokens = 0.0
        bucket._last_refill = time.monotonic()

        bucket.sync_acquire()

        assert mock_sleep.call_count == 2

        wait_call = mock_sleep.call_args_list[0].args[0]
        assert round(wait_call, 1) == 1.0

        delay_call = mock_sleep.call_args_list[1].args[0]
        assert delay_call > 0


# ---------------------------------------------------------------------------
# Adaptive Rate Limiting Tests
# ---------------------------------------------------------------------------


class TestAdaptiveRateLimiting:
    def test_report_rate_limited(self):
        """При 429 slowdown_factor умножается на 2.0 (до max 10.0)."""
        cfg = DomainConfig(adaptive=True, adaptive_slowdown=2.0, max_slowdown_factor=10.0)
        bucket = TokenBucket(cfg)

        bucket.report_rate_limited()
        assert bucket._slowdown_factor == 2.0

        bucket.report_rate_limited()
        assert bucket._slowdown_factor == 4.0

        # Упрется в лимит
        for _ in range(5):
            bucket.report_rate_limited()
        assert bucket._slowdown_factor == 10.0

    def test_report_success(self):
        """При 200 OK slowdown_factor плавно восстанавливается (x0.95), но не ниже 1.0."""
        cfg = DomainConfig(adaptive=True)
        bucket = TokenBucket(cfg)

        bucket._slowdown_factor = 2.0

        bucket.report_success()
        assert bucket._slowdown_factor == 1.9  # 2.0 * 0.95

        # Проверяем лимит "снизу"
        bucket._slowdown_factor = 1.02
        bucket.report_success()
        assert bucket._slowdown_factor == 1.0  # max(0.969, 1.0) -> 1.0

    def test_adaptive_disabled(self):
        """Если adaptive=False, факторы не меняются."""
        cfg = DomainConfig(adaptive=False)
        bucket = TokenBucket(cfg)

        bucket.report_rate_limited()
        assert bucket._slowdown_factor == 1.0

        bucket._slowdown_factor = 2.0
        bucket.report_success()
        assert bucket._slowdown_factor == 2.0
