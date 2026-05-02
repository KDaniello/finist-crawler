"""
Стресс-тест: Конкуренция за системный лок браузера.

Проверяет, что при одновременном запросе браузера от нескольких процессов,
лок гарантирует строго последовательный доступ (не более 1 браузера за раз).
"""

import multiprocessing
import time
from pathlib import Path
from typing import Any

from core.logger import setup_main_logging, stop_main_logging


def _lock_grabber_worker(
    worker_id: int,
    browser_lock: Any,
    results_queue: multiprocessing.Queue,
    log_queue: multiprocessing.Queue,
) -> None:
    """
    Воркер, который пытается захватить browser_lock.
    Записывает точные временные метки захвата и освобождения в очередь результатов.
    """
    from core.logger import setup_worker_logging

    setup_worker_logging(log_queue)

    import logging

    logger = logging.getLogger(f"LockGrabber-{worker_id}")

    logger.info(f"[{worker_id}] Ожидаю лок...")
    acquired_at = None
    released_at = None

    try:
        browser_lock.acquire()
        acquired_at = time.monotonic()
        logger.info(f"[{worker_id}] Лок захвачен!")

        # Симулируем работу браузера (парсинг одной страницы)
        time.sleep(0.5)

    finally:
        released_at = time.monotonic()
        browser_lock.release()
        logger.info(f"[{worker_id}] Лок освобожден.")

    results_queue.put(
        {
            "worker_id": worker_id,
            "acquired_at": acquired_at,
            "released_at": released_at,
        }
    )


def test_browser_lock_prevents_concurrent_access(tmp_path: Path):
    """
    СЦЕНАРИЙ: 5 процессов одновременно пытаются захватить browser_lock.
    ОЖИДАНИЕ:
    - Временные отрезки владения локом НЕ пересекаются (строгая последовательность).
    - Все 5 процессов успешно отработали (никто не завис и не упал).
    - Суммарное время >= 5 * 0.5s = 2.5s (доказывает строгую очередь, а не параллельность).
    """
    logs_dir = tmp_path / "logs"
    log_queue = setup_main_logging(logs_dir=logs_dir, debug=False)

    ctx = multiprocessing.get_context("spawn")
    browser_lock = ctx.Lock()
    results_queue = ctx.Queue()

    processes = []
    num_workers = 5

    try:
        # Запускаем всех воркеров одновременно
        for i in range(num_workers):
            p = ctx.Process(
                target=_lock_grabber_worker,
                args=(i, browser_lock, results_queue, log_queue),
                daemon=True,
            )
            p.start()
            processes.append(p)

        # Ждём завершения всех процессов (максимум 30 секунд)
        for p in processes:
            p.join(timeout=30)
            assert not p.is_alive(), f"Процесс {p.name} завис!"

        # Собираем результаты
        results = []
        while not results_queue.empty():
            results.append(results_queue.get_nowait())

    finally:
        stop_main_logging()
        log_queue.close()
        log_queue.cancel_join_thread()

    # ПРОВЕРКА 1: Все воркеры отчитались
    assert len(results) == num_workers, (
        f"Ожидали результаты от {num_workers} воркеров, получили {len(results)}"
    )

    # ПРОВЕРКА 2: Временные отрезки не пересекаются
    # Сортируем по времени захвата лока
    results.sort(key=lambda r: r["acquired_at"])

    for i in range(len(results) - 1):
        current = results[i]
        next_one = results[i + 1]

        # Следующий воркер должен захватить лок ПОСЛЕ того, как текущий его отпустил
        assert next_one["acquired_at"] >= current["released_at"], (
            f"Конкурентный доступ к браузеру! "
            f"Воркер {next_one['worker_id']} захватил лок в {next_one['acquired_at']:.3f}, "
            f"а воркер {current['worker_id']} отпустил только в {current['released_at']:.3f}"
        )

    # ПРОВЕРКА 3: Суммарное время соответствует строгой очереди
    total_time = results[-1]["released_at"] - results[0]["acquired_at"]
    expected_min_time = num_workers * 0.5  # 5 воркеров * 0.5 сек каждый
    assert total_time >= expected_min_time * 0.8, (
        f"Суммарное время {total_time:.2f}s подозрительно мало. "
        f"Ожидали минимум {expected_min_time * 0.8:.2f}s. "
        f"Возможно, лок не работает!"
    )
