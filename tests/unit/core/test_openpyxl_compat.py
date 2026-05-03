from core._openpyxl_compat import apply_openpyxl_compat


class TestOpenpyxlCompat:
    def test_apply_does_not_raise(self):
        apply_openpyxl_compat()

    def test_numeric_types_set_after_apply(self):
        apply_openpyxl_compat()
        import openpyxl.compat.numbers
        import openpyxl.compat.strings

        assert openpyxl.compat.numbers.NUMERIC_TYPES == (int, float)
        assert openpyxl.compat.strings.NUMERIC_TYPES == (int, float)
