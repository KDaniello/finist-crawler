import logging
from pathlib import Path
from typing import Any

from core.exceptions import CaptchaBlockError, NetworkError
from engine.executors import (
    ExecutorStats,
    LightExecutor,
    SaveCallback,
    StealthExecutor,
)
from engine.parsing_rules import CrawlerPlan

logger = logging.getLogger(__name__)

__all__ = ["FallbackOrchestrator"]


class FallbackOrchestrator:
    """
    Оркестратор (Цепочка ответственности).
    Определяет, какой экзекутор запускать, опираясь на стратегию в YAML (render)
    и реакцию сайта (403/Captcha).
    """

    def __init__(
        self,
        browser_lock: Any,
        profiles_dir: Path,
        render_strategy: str = "auto",
    ) -> None:
        self._browser_lock = browser_lock
        self._profiles_dir = profiles_dir
        self._render_strategy = render_strategy

    async def execute_plan(
        self, plan: CrawlerPlan, save_cb: SaveCallback, proxy_url: str | None = None
    ) -> tuple[int, ExecutorStats]:
        """
        Выполняет план парсинга, применяя Graceful Degradation.

        Стратегии:
        - "static": Только curl_cffi. Падает, если видит капчу.
        - "browser": Только Camoufox. Медленно, но надежно.
        - "auto": curl_cffi -> (если 403/Captcha) -> Camoufox.
        """
        total_records = 0
        final_stats: ExecutorStats = {}

        # ШАГ 1: Легкий парсинг (Если стратегия позволяет)
        if self._render_strategy in ("auto", "static"):
            logger.info("[FallbackChain] Запуск LightExecutor (curl_cffi)...")

            try:
                # Гарантируем закрытие C-библиотеки через async with
                # ФИКС: Прокидываем настройку impersonate из YAML в LightExecutor
                async with LightExecutor(impersonate=plan.impersonate) as light:
                    records, stats = await light.execute(plan, save_cb, proxy_url)

                total_records += records
                final_stats.update(stats)

                # Если парсинг прошел успешно до конца (или уперся в лимит страниц)
                return total_records, final_stats

            except CaptchaBlockError as e:
                logger.warning(f"🛡️ [FallbackChain] Защита от ботов: {e.detail}")
                if self._render_strategy == "static":
                    logger.error("Стратегия 'static' запрещает использовать браузер. Остановка.")
                    raise
                logger.info("[FallbackChain] Активирую Fallback -> StealthExecutor")

            except NetworkError as e:
                logger.warning(f"🌐 [FallbackChain] Сетевой сбой LightExecutor: {e}")
                if self._render_strategy == "static":
                    raise
                logger.info("[FallbackChain] Активирую Fallback -> StealthExecutor")

        # ШАГ 2: Тяжелая артиллерия (Браузер)
        if self._render_strategy in ("auto", "browser"):
            if self._browser_lock is None:
                raise RuntimeError("Критическая ошибка: Диспетчер не передал Browser Lock!")

            logger.info("[FallbackChain] Запуск StealthExecutor (Camoufox)...")

            try:
                # Экзекутор сам захватит Lock и поднимет Persistent-браузер
                async with StealthExecutor(self._browser_lock, self._profiles_dir) as stealth:
                    # Важно: мы передаем тот же plan.
                    # Если LightExecutor успел спарсить 5 страниц до бана,
                    # Stealth начнет с 6-й (если мы допишем сохранение стейта в будущем).
                    # Пока он начнет сначала, но `visited` сет (если вынести его в plan) может помочь.
                    records, stats = await stealth.execute(plan, save_cb, proxy_url)

                total_records += records
                final_stats.update(stats)

                return total_records, final_stats

            except Exception as e:
                logger.critical(
                    f"❌ [FallbackChain] Все экзекуторы потерпели краш: {e}", exc_info=True
                )
                raise NetworkError(f"Сбой финального Fallback-экзекутора: {e}") from e

        # Защита от кривого конфига
        raise ValueError(f"Неизвестная стратегия рендеринга: {self._render_strategy}")
