"""
Checks that required fonts exist in assets/fonts/.
Run: python scripts/download_fonts.py

Fonts must be downloaded manually:
  Inter:           https://github.com/rsms/inter/releases/latest
                   -> Inter-4.x.zip -> extras/ttf/
  JetBrains Mono:  https://github.com/JetBrains/JetBrainsMono/releases/latest
                   -> JetBrainsMono-*.zip -> fonts/ttf/
"""

from __future__ import annotations

import sys
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

REQUIRED_FONTS: list[tuple[str, str]] = [
    ("Inter-Regular.ttf", "Inter -> extras/ttf/Inter-Regular.ttf"),
    ("Inter-Medium.ttf", "Inter -> extras/ttf/Inter-Medium.ttf"),
    ("Inter-SemiBold.ttf", "Inter -> extras/ttf/Inter-SemiBold.ttf"),
    ("Inter-Bold.ttf", "Inter -> extras/ttf/Inter-Bold.ttf"),
    ("JetBrainsMono-Regular.ttf", "JetBrains Mono -> fonts/ttf/JetBrainsMono-Regular.ttf"),
]

MIN_SIZE_BYTES = 10 * 1024  # minimum 10 KB


def check_fonts() -> bool:
    print("=== Finist Crawler - Font Check ===")
    print(f"Directory: {FONTS_DIR}\n")

    if not FONTS_DIR.exists():
        print(f"[error] Directory not found: {FONTS_DIR}")
        print("        Create the directory and place fonts inside.")
        return False

    all_ok = True

    for filename, hint in REQUIRED_FONTS:
        path = FONTS_DIR / filename

        if not path.exists():
            print(f"  x {filename}")
            print(f"    Source: {hint}")
            all_ok = False
            continue

        size = path.stat().st_size
        if size < MIN_SIZE_BYTES:
            print(
                f"  x {filename} - corrupted ({size} bytes, expected > {MIN_SIZE_BYTES // 1024} KB)"
            )
            print(f"    Source: {hint}")
            all_ok = False
            continue

        size_kb = size // 1024
        print(f"  ok {filename} ({size_kb} KB)")

    return all_ok


def main() -> None:
    ok = check_fonts()

    if ok:
        print(f"\nAll fonts ready ({len(REQUIRED_FONTS)} files)")
    else:
        print("\nFonts missing or corrupted.")
        print("\nInstructions:")
        print("  Inter:          https://github.com/rsms/inter/releases/latest")
        print("                  Download Inter-4.x.zip -> extras/ttf/")
        print("  JetBrains Mono: https://github.com/JetBrains/JetBrainsMono/releases/latest")
        print("                  Download JetBrainsMono-*.zip -> fonts/ttf/")
        print(f"\n  Place files in: {FONTS_DIR}")
        sys.exit(1)


if __name__ == "__main__":
    main()
