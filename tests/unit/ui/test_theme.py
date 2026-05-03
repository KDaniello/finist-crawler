from ui.theme import DARK, LIGHT, ColorTokens, ThemeController


class TestColorTokens:
    def test_dark_tokens_exist(self):
        assert isinstance(DARK, ColorTokens)
        assert DARK.bg_primary == "#0F0F0F"
        assert DARK.accent == "#22C55E"

    def test_light_tokens_exist(self):
        assert isinstance(LIGHT, ColorTokens)
        assert LIGHT.bg_primary == "#FFFFFF"
        assert LIGHT.accent == "#16A34A"


class TestThemeController:
    def test_default_is_dark(self):
        ctrl = ThemeController()
        assert ctrl.is_dark is True
        assert ctrl.tokens is DARK

    def test_light_mode(self):
        ctrl = ThemeController(is_dark=False)
        assert ctrl.is_dark is False
        assert ctrl.tokens is LIGHT

    def test_toggle(self):
        ctrl = ThemeController(is_dark=True)
        ctrl.toggle()
        assert ctrl.is_dark is False
        assert ctrl.tokens is LIGHT
        ctrl.toggle()
        assert ctrl.is_dark is True
        assert ctrl.tokens is DARK

    def test_set_dark(self):
        ctrl = ThemeController(is_dark=True)
        ctrl.set_dark(False)
        assert ctrl.is_dark is False
        ctrl.set_dark(True)
        assert ctrl.is_dark is True
