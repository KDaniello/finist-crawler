from __future__ import annotations

import pytest

from ui.theme import (
    DARK,
    FONT_DISPLAY,
    FONT_MONO,
    FONT_TEXT,
    LIGHT,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    RADIUS_XL,
    SIZE_BODY,
    SIZE_CAPTION,
    SIZE_HEADING,
    SIZE_LABEL,
    SIZE_TITLE,
    SPACE_2XL,
    SPACE_3XL,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    ColorTokens,
    ThemeController,
)


class TestColorTokens:
    def test_dark_tokens_frozen(self) -> None:
        assert isinstance(DARK, ColorTokens)
        assert DARK.bg_primary == "#1C1C1E"
        assert DARK.accent == "#0A84FF"

    def test_light_tokens_frozen(self) -> None:
        assert isinstance(LIGHT, ColorTokens)
        assert LIGHT.bg_primary == "#F2F2F7"
        assert LIGHT.accent == "#007AFF"

    def test_dark_has_all_new_fields(self) -> None:
        assert DARK.accent_light is not None
        assert DARK.success is not None
        assert DARK.warning is not None
        assert DARK.error is not None
        assert DARK.neutral is not None
        assert DARK.text_tertiary is not None
        assert DARK.bg_overlay is not None
        assert DARK.border_light is not None
        assert DARK.border_medium is not None

    def test_light_has_all_new_fields(self) -> None:
        assert LIGHT.accent_light is not None
        assert LIGHT.success is not None
        assert LIGHT.warning is not None
        assert LIGHT.error is not None
        assert LIGHT.neutral is not None
        assert LIGHT.text_tertiary is not None
        assert LIGHT.bg_overlay is not None
        assert LIGHT.border_light is not None
        assert LIGHT.border_medium is not None

    def test_dark_has_legacy_fields(self) -> None:
        assert DARK.bg_secondary is not None
        assert DARK.bg_elevated is not None
        assert DARK.bg_input is not None
        assert DARK.accent_hover is not None
        assert DARK.accent_danger is not None
        assert DARK.accent_warn is not None
        assert DARK.accent_info is not None
        assert DARK.text_muted is not None
        assert DARK.border is not None
        assert DARK.border_focus is not None

    def test_light_has_legacy_fields(self) -> None:
        assert LIGHT.bg_secondary is not None
        assert LIGHT.bg_elevated is not None
        assert LIGHT.bg_input is not None
        assert LIGHT.accent_hover is not None
        assert LIGHT.accent_danger is not None
        assert LIGHT.accent_warn is not None
        assert LIGHT.accent_info is not None
        assert LIGHT.text_muted is not None
        assert LIGHT.border is not None
        assert LIGHT.border_focus is not None

    def test_dark_frozen(self) -> None:
        with pytest.raises(AttributeError):
            DARK.accent = "#000000"  # type: ignore[misc]

    def test_light_frozen(self) -> None:
        with pytest.raises(AttributeError):
            LIGHT.accent = "#000000"  # type: ignore[misc]


class TestTypographyConstants:
    def test_font_names_are_strings(self) -> None:
        assert isinstance(FONT_DISPLAY, str)
        assert isinstance(FONT_TEXT, str)
        assert isinstance(FONT_MONO, str)

    def test_size_constants(self) -> None:
        assert SIZE_TITLE == 28
        assert SIZE_HEADING == 20
        assert SIZE_BODY == 15
        assert SIZE_LABEL == 13
        assert SIZE_CAPTION == 11


class TestSpacingConstants:
    def test_space_values(self) -> None:
        assert SPACE_XS == 4
        assert SPACE_SM == 8
        assert SPACE_MD == 16
        assert SPACE_LG == 24
        assert SPACE_XL == 32
        assert SPACE_2XL == 48
        assert SPACE_3XL == 64


class TestRadiusConstants:
    def test_radius_values(self) -> None:
        assert RADIUS_SM == 8
        assert RADIUS_MD == 12
        assert RADIUS_LG == 16
        assert RADIUS_XL == 20


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
