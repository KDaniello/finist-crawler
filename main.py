"""
Точка входа Finist Crawler.
Этот файл используется PyInstaller как target.
В dev-режиме можно запускать напрямую: python main.py
"""

from __future__ import annotations

import multiprocessing


def main() -> None:
    multiprocessing.freeze_support()

    # Настройка окружения (создание директорий, proxies.txt)
    from core.config import setup_environment

    setup_environment()

    # Запуск Flet приложения
    import flet as ft

    from ui.app import main as app_main

    ft.app(target=app_main)


if __name__ == "__main__":
    main()
