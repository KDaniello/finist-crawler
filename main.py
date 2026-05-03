"""
Точка входа Finist Crawler.
Этот файл используется PyInstaller как target.
В dev-режиме можно запускать напрямую: python main.py
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable


def main() -> None:
    multiprocessing.freeze_support()

    from core.config import setup_environment

    setup_environment()

    from bots.universal_bot import run_universal_bot

    import flet as ft

    from ui.app import main as app_main

    def flet_target(page: ft.Page) -> None:
        app_main(page, worker_target=run_universal_bot)

    ft.app(target=flet_target)


if __name__ == "__main__":
    main()
