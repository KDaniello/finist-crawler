# mypy: disable-error-code=no-untyped-def
# ruff: noqa: RUF001, RUF002, RUF003

"""
Тесты для core/exceptions.py

Покрытие: 100%
- Проверка иерархии наследования всех исключений (isinstance/issubclass)
- Проверка инициализации базовых исключений
- Проверка кастомных аргументов и форматирования сообщений для RateLimitError
- Проверка кастомных аргументов и форматирования сообщений для CaptchaBlockError
"""

from core.exceptions import (
    CaptchaBlockError,
    ConfigurationError,
    FinistError,
    NetworkError,
    ParsingError,
    RateLimitError,
)


class TestFinistExceptions:
    def test_base_exception_inheritance(self):
        """Все кастомные ошибки должны наследоваться от FinistError, а он от Exception."""
        assert issubclass(FinistError, Exception)

        child_exceptions = [
            ConfigurationError,
            ParsingError,
            NetworkError,
            RateLimitError,
            CaptchaBlockError,
        ]
        for exc in child_exceptions:
            assert issubclass(exc, FinistError)

    def test_basic_exceptions_instantiation(self):
        """Базовые исключения принимают строковое сообщение и сохраняют его."""
        err1 = ConfigurationError("Кривой YAML")
        assert str(err1) == "Кривой YAML"

        err2 = ParsingError("Не найден селектор")
        assert str(err2) == "Не найден селектор"

        err3 = NetworkError("Таймаут соединения")
        assert str(err3) == "Таймаут соединения"

    def test_rate_limit_error(self):
        """RateLimitError сохраняет url, retry_after и формирует правильное сообщение."""
        # С дефолтным retry_after = 5
        err_default = RateLimitError(url="https://example.com")
        assert err_default.url == "https://example.com"
        assert err_default.retry_after == 5
        assert str(err_default) == "Превышен лимит запросов к https://example.com. Пауза 5с."

        # С кастомным retry_after
        err_custom = RateLimitError(url="https://api.com", retry_after=60)
        assert err_custom.url == "https://api.com"
        assert err_custom.retry_after == 60
        assert "Пауза 60с." in str(err_custom)

    def test_captcha_block_error(self):
        """CaptchaBlockError сохраняет url, detail и формирует правильное сообщение."""
        # С дефолтным detail (пустая строка)
        err_default = CaptchaBlockError(url="https://cloudflare.com")
        assert err_default.url == "https://cloudflare.com"
        assert err_default.detail == ""
        assert str(err_default) == "Обнаружена защита (Капча/Блок) на https://cloudflare.com: "

        # С указанным detail
        err_custom = CaptchaBlockError(url="https://reddit.com", detail="403 Forbidden")
        assert err_custom.url == "https://reddit.com"
        assert err_custom.detail == "403 Forbidden"
        assert (
            str(err_custom) == "Обнаружена защита (Капча/Блок) на https://reddit.com: 403 Forbidden"
        )
