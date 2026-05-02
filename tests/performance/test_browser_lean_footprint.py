"""
Performance тест: Потребление памяти тяжелым браузером (Camoufox).

ВАЖНО: Этот тест запускается ОТДЕЛЬНО от основного сьюта,
так как реальный браузер несовместим с моками из unit-тестов.

Команда запуска:
    pytest tests/performance/test_browser_lean_footprint.py -v -s
"""

import asyncio
from pathlib import Path

import pytest

from core.resources import SystemMonitor
from engine.browser import ImmortalBrowser


@pytest.mark.asyncio
async def test_browser_ram_footprint(browser_lock, tmp_path: Path):
    """
    СЦЕНАРИЙ: Поднимаем реальный браузер (Camoufox) и держим его открытым.
    ОЖИДАНИЕ: Суммарное потребление RAM < 1500 МБ.
    """
    monitor = SystemMonitor()

    base_stats = monitor.get_stats()
    base_ram_mb = base_stats.app_memory_mb

    await asyncio.to_thread(browser_lock.acquire)

    try:
        async with ImmortalBrowser(domain="test_domain", profiles_dir=tmp_path) as browser:
            await asyncio.sleep(3.0)

            if browser.page:
                await browser.page.goto("https://example.com", wait_until="domcontentloaded")
                await asyncio.sleep(2.0)

            active_stats = monitor.get_stats()
            total_ram_mb = active_stats.app_memory_mb
            browser_weight_mb = total_ram_mb - base_ram_mb

            print(
                f"\n[PERF] База: {base_ram_mb:.0f} MB | "
                f"С браузером: {total_ram_mb:.0f} MB | "
                f"Вес браузера: {browser_weight_mb:.0f} MB"
            )

            assert browser_weight_mb < 1500.0, (
                f"Браузер слишком тяжелый: {browser_weight_mb:.0f} MB"
            )

    finally:
        browser_lock.release()
