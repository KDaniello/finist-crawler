from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ui.theme import DARK, LIGHT, ColorTokens, ThemeController


class TestColorTokens:
    def test_dark_tokens_are_frozen(self) -> None:
        assert isinstance(DARK, ColorTokens)
        assert DARK.bg_primary == "#0F0F0F"
        assert DARK.accent == "#22C55E"

    def test_light_tokens_are_frozen(self) -> None:
        assert isinstance(LIGHT, ColorTokens)
        assert LIGHT.bg_primary == "#FFFFFF"
        assert LIGHT.accent == "#16A34A"


class TestThemeController:
    def test_default_is_dark(self) -> None:
        tc = ThemeController()
        assert tc.is_dark is True

    def test_init_light(self) -> None:
        tc = ThemeController(is_dark=False)
        assert tc.is_dark is False

    def test_tokens_dark(self) -> None:
        tc = ThemeController(is_dark=True)
        assert tc.tokens is DARK

    def test_tokens_light(self) -> None:
        tc = ThemeController(is_dark=False)
        assert tc.tokens is LIGHT

    def test_toggle_dark_to_light(self) -> None:
        tc = ThemeController(is_dark=True)
        tc.toggle()
        assert tc.is_dark is False
        assert tc.tokens is LIGHT

    def test_toggle_light_to_dark(self) -> None:
        tc = ThemeController(is_dark=False)
        tc.toggle()
        assert tc.is_dark is True
        assert tc.tokens is DARK

    def test_set_dark(self) -> None:
        tc = ThemeController(is_dark=True)
        tc.set_dark(False)
        assert tc.is_dark is False

    def test_set_dark_true(self) -> None:
        tc = ThemeController(is_dark=False)
        tc.set_dark(True)
        assert tc.is_dark is True
