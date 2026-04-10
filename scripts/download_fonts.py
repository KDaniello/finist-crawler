"""
Проверяет наличие шрифтов в assets/fonts/.
Запуск: python scripts/download_fonts.py

Шрифты скачиваются вручную:
  Inter:           https://github.com/rsms/inter/releases/latest
                   → Inter-4.x.zip → extras/ttf/
  JetBrains Mono:  https://github.com/JetBrains/JetBrainsMono/releases/latest
                   → JetBrainsMono-*.zip → fonts/ttf/
"""

from __future__ import annotations

import sys
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

REQUIRED_FONTS: list[tuple[str, str]] = [
    ("Inter-Regular.ttf", "Inter → extras/ttf/Inter-Regular.ttf"),
    ("Inter-Medium.ttf", "Inter → extras/ttf/Inter-Medium.ttf"),
    ("Inter-SemiBold.ttf", "Inter → extras/ttf/Inter-SemiBold.ttf"),
    ("Inter-Bold.ttf", "Inter → extras/ttf/Inter-Bold.ttf"),
    ("JetBrainsMono-Regular.ttf", "JetBrains Mono → fonts/ttf/JetBrainsMono-Regular.ttf"),
]

MIN_SIZE_BYTES = 10 * 1024  # минимум 10 KB — защита от пустых файлов


def check_fonts() -> bool:
    """Проверяет наличие и размер всех шрифтов. Возвращает True если всё ок."""
    print("=== Finist Crawler — Проверка шрифтов ===")
    print(f"Папка: {FONTS_DIR}\n")

    if not FONTS_DIR.exists():
        print(f"[error] Папка не существует: {FONTS_DIR}")
        print("        Создайте папку и положите в неё шрифты.")
        return False

    all_ok = True

    for filename, hint in REQUIRED_FONTS:
        path = FONTS_DIR / filename

        if not path.exists():
            print(f"  ✗ {filename}")
            print(f"    Источник: {hint}")
            all_ok = False
            continue

        size = path.stat().st_size
        if size < MIN_SIZE_BYTES:
            print(
                f"  ✗ {filename} — повреждён ({size} байт, ожидается > {MIN_SIZE_BYTES // 1024} KB)"
            )
            print(f"    Источник: {hint}")
            all_ok = False
            continue

        size_kb = size // 1024
        print(f"  ✓ {filename} ({size_kb} KB)")

    return all_ok


def main() -> None:
    ok = check_fonts()

    if ok:
        print(f"\n✅ Все шрифты на месте ({len(REQUIRED_FONTS)} файлов)")
    else:
        print("\n❌ Шрифты не найдены или повреждены.")
        print("\nИнструкция:")
        print("  Inter:          https://github.com/rsms/inter/releases/latest")
        print("                  Скачай Inter-4.x.zip → extras/ttf/")
        print("  JetBrains Mono: https://github.com/JetBrains/JetBrainsMono/releases/latest")
        print("                  Скачай JetBrainsMono-*.zip → fonts/ttf/")
        print(f"\n  Положи файлы в: {FONTS_DIR}")
        sys.exit(1)


if __name__ == "__main__":
    main()
