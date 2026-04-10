from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class JobConfig:
    """
    Типизированная конфигурация задачи парсинга.

    Заменяет голый dict[str, Any] при передаче параметров
    от UI через Dispatcher в universal_bot.

    Attributes:
        spec_name: Имя YAML файла спецификации.
        max_pages: Лимит страниц list-этапа.
        detail_max_pages: Лимит страниц detail-этапа (0 = без ограничений).
        template_params: Параметры для подстановки в URL шаблоны.
        direct_urls: Прямые URL (минуя шаблоны).

    Example:
        >>> cfg = JobConfig(spec_name="habr_search.yaml",
        ...                 template_params={"keyword": "Python"})
        >>> dispatcher.start_tasks(worker, [cfg.spec_name], cfg.to_dict())
    """

    spec_name: str = ""
    max_pages: int = 5
    detail_max_pages: int = 0
    template_params: dict[str, str] = field(default_factory=dict)
    direct_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """
        Конвертирует в dict для обратной совместимости с build_plan().

        Returns:
            Словарь в формате config_overrides.
        """
        return {
            "max_pages": self.max_pages,
            "detail_max_pages": self.detail_max_pages,
            "template_params": self.template_params,
            "direct_urls": self.direct_urls,
        }

    @classmethod
    def from_dict(cls, spec_name: str, overrides: dict[str, Any]) -> JobConfig:
        """
        Создаёт JobConfig из старого формата dict.

        Args:
            spec_name: Имя файла спецификации.
            overrides: Словарь config_overrides старого формата.

        Returns:
            Новый экземпляр JobConfig.
        """
        return cls(
            spec_name=spec_name,
            max_pages=overrides.get("max_pages", 5),
            detail_max_pages=overrides.get("detail_max_pages", 0),
            template_params=overrides.get("template_params", {}),
            direct_urls=overrides.get("direct_urls", []),
        )
