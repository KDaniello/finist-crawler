from collections.abc import Callable
from types import TracebackType
from typing import Any, Protocol

# Импортируем наш типизированный план парсинга
from engine.parsing_rules import CrawlerPlan

__all__ = ["ExecutorStats", "IExecutor"]

# Псевдоним типа для статистики работы экзекутора (чтобы не использовать голый Dict)
ExecutorStats = dict[str, Any]

# Псевдоним типа для коллбека сохранения (передается извне)
SaveCallback = Callable[[list[dict[str, Any]]], None]


class IExecutor(Protocol):
    """
    Контракт (Интерфейс) для всех исполнителей парсинга (Light, Stealth).
    Использует duck-typing: любой класс, реализующий эти методы, является экзекутором.
    """

    @property
    def name(self) -> str:
        """Уникальное имя экзекутора (например: 'LightExecutor', 'CamoufoxStealth')."""
        ...

    async def __aenter__(self) -> "IExecutor":
        """Асинхронный контекстный менеджер (инициализация сессий/браузеров)."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Гарантированное освобождение ресурсов (закрытие вкладок, сокетов)."""
        ...

    async def execute(
        self, plan: CrawlerPlan, save_cb: SaveCallback, proxy_url: str | None = None
    ) -> tuple[int, ExecutorStats]:
        """
        Главный метод извлечения данных.

        Args:
            plan: Спецификация обхода (URL, селекторы, лимиты).
            save_cb: Функция обратного вызова для атомарного сброса данных на диск (каждые N страниц).
            proxy_url: Строка прокси (http://user:pass@ip:port).

        Returns:
            Tuple[int, ExecutorStats]: Количество сохраненных записей и словарь со статистикой работы.

        Raises:
            CaptchaBlockError: Если экзекутор поймал защиту (сигнал для Fallback Chain).
            NetworkError: Если сайт недоступен.
        """
        ...
