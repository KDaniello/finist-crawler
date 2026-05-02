def apply_openpyxl_compat() -> None:
    try:
        import openpyxl.compat.numbers

        openpyxl.compat.numbers.NUMERIC_TYPES = (int, float)

        import openpyxl.compat.strings

        openpyxl.compat.strings.NUMERIC_TYPES = (int, float)
    except ImportError:
        pass
