import asyncio
import logging
import multiprocessing
from typing import Any

from core import DataWriter, get_paths, get_settings, setup_worker_logging
from engine import CrawlerPlan, FallbackOrchestrator, build_plan, load_spec

logger = logging.getLogger(__name__)

__all__ = ["run_universal_bot"]


def run_universal_bot(
    spec_name: str,
    session_id: str,
    config_overrides: dict[str, Any],
    log_queue: multiprocessing.Queue,
    browser_lock: Any,
) -> None:
    setup_worker_logging(log_queue)
    settings = get_settings()
    paths = get_paths()

    logger.name = f"Bot-{spec_name}"
    logger.info(f"🚀 Процесс парсинга запущен (Session: {session_id[:8]}...)")

    async def _async_run() -> None:
        try:
            # 1. Ядро само разберется с шаблонами URL
            spec_data = load_spec(spec_name, paths.specs_dir)
            plan: CrawlerPlan = build_plan(spec_data, config_overrides)

            source_key = spec_data.get(
                "source_key", spec_name.replace(".yaml", "").replace(".yml", "")
            )

            # 2. Инициализация писателя
            writer = DataWriter(
                base_dir=paths.data_dir,
                session_id=session_id,
                source=source_key,
                lock=multiprocessing.Lock(),
            )

            def save_records(records: list[dict[str, Any]]) -> None:
                if records:
                    writer.save_batch(records)

            # 3. Запуск оркестратора
            orchestrator = FallbackOrchestrator(
                browser_lock=browser_lock,
                profiles_dir=paths.profiles_dir,
                render_strategy=plan.render_strategy,
            )

            logger.info(
                f"План построен: стартовых URL: {len(plan.start_urls)}, стратегия: {plan.render_strategy}"
            )

            total_saved, stats = await orchestrator.execute_plan(
                plan=plan, save_cb=save_records, proxy_url=settings.PROXY_URL
            )

            logger.info(
                f"✅ Парсинг [{spec_name}] успешно завершен!\n"
                f"📊 Статистика: {stats}\n"
                f"💾 Сохранено записей: {total_saved}"
            )

        except asyncio.CancelledError:
            logger.warning(f"⚠️ Процесс [{spec_name}] принудительно остановлен пользователем.")
        except Exception as e:
            logger.critical(f"❌ Критическая ошибка в боте [{spec_name}]: {e}", exc_info=True)
        finally:
            logger.info(f"🏁 Процесс [{spec_name}] завершает работу.")

    try:
        asyncio.run(_async_run())
    except KeyboardInterrupt:
        pass
