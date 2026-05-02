__all__ = [
    "CaptchaBlockError",
    "ConfigurationError",
    "FinistError",
    "NetworkError",
    "ParsingError",
    "RateLimitError",
]


class FinistError(Exception):
    """Базовый класс для всех кастомных исключений проекта."""


# --- Ошибки инициализации и конфигурации ---


class ConfigurationError(FinistError):
    """Ошибка в настройках (например, кривой YAML или отсутствие путей)."""


# --- Ошибки парсинга данных ---


class ParsingError(FinistError):
    """Ошибка извлечения данных (изменилась верстка, не найден селектор)."""


# --- Сетевые ошибки и блокировки (Executors) ---


class NetworkError(FinistError):
    """Общая сетевая ошибка (таймаут, DNS, Connection Reset)."""


class RateLimitError(FinistError):
    """Получен статус 429 (Too Many Requests). Требуется пауза."""

    def __init__(self, url: str, retry_after: int = 5) -> None:
        self.url = url
        self.retry_after = retry_after
        super().__init__(f"Превышен лимит запросов к {url}. Пауза {retry_after}с.")


class CaptchaBlockError(FinistError):
    """
    Критическая блокировка (Cloudflare, 403 Forbidden, ReCaptcha).
    Служит триггером для перехода на StealthExecutor (Camoufox).
    """

    def __init__(self, url: str, detail: str = "") -> None:
        self.url = url
        self.detail = detail
        super().__init__(f"Обнаружена защита (Капча/Блок) на {url}: {detail}")
