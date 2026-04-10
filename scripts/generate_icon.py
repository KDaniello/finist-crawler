"""
Генерирует иконку приложения assets/icon.ico через Pillow.
Запуск: python scripts/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[error] Pillow не установлен: pip install Pillow")
    raise

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.ico"

# Цвета из дизайн-системы Finist
COLOR_BG = (15, 15, 15)  # #0F0F0F — тёмный фон
COLOR_ACCENT = (34, 197, 94)  # #22C55E — зелёный акцент


def generate_icon() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 256]
    frames: list[Image.Image] = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Скруглённый прямоугольник как фон
        radius = size // 6
        draw.rounded_rectangle(
            [0, 0, size - 1, size - 1],
            radius=radius,
            fill=COLOR_BG,
        )

        # Буква "F" по центру
        font_size = int(size * 0.55)
        font: ImageFont.ImageFont | ImageFont.FreeTypeFont
        try:
            # Пробуем найти Arial на Windows
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
                )
            except OSError:
                font = ImageFont.load_default()

        # Центрируем текст
        bbox = draw.textbbox((0, 0), "F", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (size - text_w) // 2 - bbox[0]
        y = (size - text_h) // 2 - bbox[1]

        draw.text((x, y), "F", fill=COLOR_ACCENT, font=font)

        frames.append(img)

    # Сохраняем как .ico со всеми размерами
    frames[0].save(
        ICON_PATH,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"✅ Иконка сохранена: {ICON_PATH}")
    print(f"   Размеры: {sizes}")


if __name__ == "__main__":
    generate_icon()
