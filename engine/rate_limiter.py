import asyncio
import logging
import random
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["DomainConfig", "TokenBucket"]


@dataclass(frozen=True)
class DomainConfig:
    """
    Настройки Rate Limiting для конкретного домена.
    frozen=True гарантирует неизменяемость конфига во время работы.
    """

    requests_per_second: float = 1.0
    burst_size: int = 1
    min_delay_ms: float = 1000.0
    max_delay_ms: float = 3000.0
    adaptive: bool = True
    adaptive_slowdown: float = 2.0  # Во сколько раз замедляемся при 429
    max_slowdown_factor: float = 10.0  # Максимальное замедление
    jitter_factor: float = 0.2  # +/- 20% к задержке для имитации человека


class TokenBucket:
    """
    Универсальный локальный Token Bucket + Human Delay.
    Поддерживает как асинхронный (curl_cffi), так и синхронный (Camoufox) парсинг.
    """

    def __init__(self, config: DomainConfig):
        self._cfg = config
        self._max_tokens: float = float(config.burst_size)
        self._tokens: float = self._max_tokens
        self._rate: float = config.requests_per_second

        self._last_refill: float = time.monotonic()
        self._slowdown_factor: float = 1.0

        # Ленивая инициализация асинхронного лока для защиты от RuntimeError
        self._async_lock: asyncio.Lock | None = None

    def _refill(self) -> None:
        """Пополняет корзину токенов на основе прошедшего времени."""
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_refill)

        effective_rate = self._rate / self._slowdown_factor
        new_tokens = elapsed * effective_rate

        self._tokens = min(self._tokens + new_tokens, self._max_tokens)
        self._last_refill = now

    def _get_human_delay(self) -> float:
        """Вычисляет рандомизированную задержку, имитирующую человека."""
        base_min = (self._cfg.min_delay_ms / 1000.0) * self._slowdown_factor
        base_max = (self._cfg.max_delay_ms / 1000.0) * self._slowdown_factor

        delay = random.uniform(base_min, base_max)
        jitter_val = delay * self._cfg.jitter_factor

        final_delay = delay + random.uniform(-jitter_val, jitter_val)
        return max(final_delay, 0.1)  # Защита от отрицательных чисел

    def _calculate_wait_time(self) -> float:
        """Обновляет токены и возвращает время, которое нужно подождать до следующего."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0

        # Математически вычисляем точное время до появления 1 токена
        effective_rate = self._rate / self._slowdown_factor
        time_to_wait = (1.0 - self._tokens) / effective_rate
        return max(time_to_wait, 0.0)

    # --- ASYNC АПИ (Для LightExecutor / curl_cffi) ---

    async def acquire(self) -> None:
        """Асинхронное получение токена + пауза."""
        # ФИКС: Безопасная инициализация
        if not hasattr(self, "_async_lock") or self._async_lock is None:
            self._async_lock = asyncio.Lock()

        async with self._async_lock:
            wait_time = self._calculate_wait_time()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                self._tokens -= 1.0
                self._last_refill = time.monotonic()

        human_delay = self._get_human_delay()
        logger.debug(
            f"[RateLimiter] Пауза {human_delay:.1f}s (slowdown={self._slowdown_factor:.1f}x)"
        )
        await asyncio.sleep(human_delay)

    # --- SYNC АПИ (Для StealthExecutor / Camoufox) ---

    def sync_acquire(self) -> None:
        """Синхронное получение токена + пауза (блокирует текущий поток)."""
        wait_time = self._calculate_wait_time()
        if wait_time > 0:
            time.sleep(wait_time)
            self._tokens -= 1.0
            self._last_refill = time.monotonic()

        human_delay = self._get_human_delay()
        logger.debug(f"[RateLimiter] [SYNC] Пауза {human_delay:.1f}s")
        time.sleep(human_delay)

    # --- УПРАВЛЕНИЕ АДАПТИВНОСТЬЮ ---

    def report_rate_limited(self) -> None:
        """Реакция на 429 Too Many Requests (Экстренное торможение)."""
        if not self._cfg.adaptive:
            return

        new_factor = self._slowdown_factor * self._cfg.adaptive_slowdown
        self._slowdown_factor = min(new_factor, self._cfg.max_slowdown_factor)
        logger.warning(
            f"🚨 [RateLimiter] Получен 429/Капча! Замедляем парсинг в {self._slowdown_factor:.1f}x раз."
        )

    def report_success(self) -> None:
        """Плавное возвращение к нормальной скорости при успешных ответах."""
        if not self._cfg.adaptive or self._slowdown_factor <= 1.0:
            return

        self._slowdown_factor = max(self._slowdown_factor * 0.95, 1.0)
