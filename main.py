"""
Точка входа Finist Crawler.
Этот файл используется PyInstaller как target.
В dev-режиме можно запускать напрямую: python main.py
"""

from __future__ import annotations

import multiprocessing


def main() -> None:
    multiprocessing.freeze_support()

    from core.config import get_paths, setup_environment

    setup_environment()

    import flet as ft

    from bots.universal_bot import run_universal_bot
    from engine.spec_loader import discover_sources
    from ui.app import main as app_main

    paths = get_paths()

    try:
        sources = discover_sources(paths.specs_dir)
    except Exception:
        sources = []

    def flet_target(page: ft.Page) -> None:
        app_main(page, worker_target=run_universal_bot, sources=sources)

    ft.app(target=flet_target)


if __name__ == "__main__":
    main()
