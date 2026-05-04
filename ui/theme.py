from __future__ import annotations

from dataclasses import dataclass

FONT_DISPLAY = "Inter Display"
FONT_TEXT = "Inter"
FONT_MONO = "JetBrains Mono"

SIZE_TITLE = 28
SIZE_HEADING = 20
SIZE_BODY = 15
SIZE_LABEL = 13
SIZE_CAPTION = 11

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32
SPACE_2XL = 48
SPACE_3XL = 64

RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16
RADIUS_XL = 20


@dataclass(frozen=True)
class ColorTokens:
    """Цветовые токены дизайн-системы."""

    bg_primary: str
    bg_secondary: str
    bg_elevated: str
    bg_input: str
    bg_overlay: str

    accent: str
    accent_hover: str
    accent_light: str
    accent_danger: str
    accent_warn: str
    accent_info: str

    success: str
    warning: str
    error: str
    neutral: str

    text_primary: str
    text_secondary: str
    text_muted: str
    text_tertiary: str

    border: str
    border_focus: str
    border_light: str
    border_medium: str


DARK = ColorTokens(
    bg_primary="#1C1C1E",
    bg_secondary="#2C2C2E",
    bg_elevated="#3A3A3C",
    bg_input="#2C2C2E",
    bg_overlay="#343436",
    accent="#0A84FF",
    accent_hover="#409CFF",
    accent_light="#1C3A5C",
    accent_danger="#FF453A",
    accent_warn="#FF9F0A",
    accent_info="#0A84FF",
    success="#30D158",
    warning="#FF9F0A",
    error="#FF453A",
    neutral="#8E8E93",
    text_primary="#FFFFFF",
    text_secondary="#EBEBF5",
    text_muted="#636366",
    text_tertiary="#48484A",
    border="#38383A",
    border_focus="#0A84FF",
    border_light="#38383A",
    border_medium="#545458",
)

LIGHT = ColorTokens(
    bg_primary="#F2F2F7",
    bg_secondary="#FFFFFF",
    bg_elevated="#FFFFFF",
    bg_input="#FFFFFF",
    bg_overlay="#F9F9FB",
    accent="#007AFF",
    accent_hover="#0056CC",
    accent_light="#E8F0FE",
    accent_danger="#FF3B30",
    accent_warn="#FF9F0A",
    accent_info="#007AFF",
    success="#34C759",
    warning="#FF9F0A",
    error="#FF3B30",
    neutral="#8E8E93",
    text_primary="#1C1C1E",
    text_secondary="#6C6C70",
    text_muted="#AEAEB2",
    text_tertiary="#C7C7CC",
    border="#E5E5EA",
    border_focus="#007AFF",
    border_light="#E5E5EA",
    border_medium="#C7C7CC",
)


class ThemeController:
    """
    Управляет активной темой приложения.

    Singleton — один экземпляр на всё приложение,
    передаётся через AppController.
    """

    def __init__(self, is_dark: bool = True) -> None:
        self._is_dark = is_dark

    @property
    def is_dark(self) -> bool:
        return self._is_dark

    @property
    def tokens(self) -> ColorTokens:
        return DARK if self._is_dark else LIGHT

    def toggle(self) -> None:
        self._is_dark = not self._is_dark

    def set_dark(self, value: bool) -> None:
        self._is_dark = value
