from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColorTokens:
    """Цветовые токены дизайн-системы."""

    bg_primary: str
    bg_secondary: str
    bg_elevated: str
    bg_input: str

    accent: str
    accent_hover: str
    accent_danger: str
    accent_warn: str
    accent_info: str

    text_primary: str
    text_secondary: str
    text_muted: str

    border: str
    border_focus: str


DARK = ColorTokens(
    bg_primary="#0F0F0F",
    bg_secondary="#1A1A1A",
    bg_elevated="#242424",
    bg_input="#1A1A1A",
    accent="#22C55E",
    accent_hover="#16A34A",
    accent_danger="#EF4444",
    accent_warn="#F59E0B",
    accent_info="#3B82F6",
    text_primary="#FFFFFF",
    text_secondary="#A1A1AA",
    text_muted="#52525B",
    border="#27272A",
    border_focus="#22C55E",
)

LIGHT = ColorTokens(
    bg_primary="#FFFFFF",
    bg_secondary="#FAFAFA",
    bg_elevated="#F4F4F5",
    bg_input="#FFFFFF",
    accent="#16A34A",
    accent_hover="#15803D",
    accent_danger="#DC2626",
    accent_warn="#D97706",
    accent_info="#2563EB",
    text_primary="#09090B",
    text_secondary="#71717A",
    text_muted="#A1A1AA",
    border="#E4E4E7",
    border_focus="#16A34A",
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
