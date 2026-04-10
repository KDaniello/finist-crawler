from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TelemetryEventType(Enum):
    """Типы телеметрических событий от воркеров."""

    PAGE_START = "page_start"
    PROGRESS = "progress"
    BRANCH_DONE = "branch_done"
    CAPTCHA_WAITING = "captcha_waiting"
    CAPTCHA_SOLVED = "captcha_solved"
    WORKER_DONE = "worker_done"
    WORKER_ERROR = "worker_error"


@dataclass
class TelemetryEvent:
    """
    Типизированное событие телеметрии от воркера.

    Attributes:
        event_type: Тип события.
        spec_name: Имя спецификации источника.
        page_number: Номер страницы (для PAGE_START).
        branch_url: URL ветки парсинга (для PROGRESS/BRANCH_DONE).
        current: Текущее количество записей.
        total: Ожидаемое количество (-1 если неизвестно).
        seconds_remaining: Секунд до таймаута (для CAPTCHA_WAITING).
        error_message: Сообщение об ошибке (для WORKER_ERROR).
    """

    event_type: TelemetryEventType
    spec_name: str = ""
    page_number: int | None = None
    branch_url: str | None = None
    current: int | None = None
    total: int | None = None
    seconds_remaining: int | None = None
    error_message: str | None = None

    @classmethod
    def from_log_message(cls, msg: str) -> TelemetryEvent | None:
        """
        Парсит строку TELEMETRY| из лога в типизированный объект.

        Args:
            msg: Строка лога вида "TELEMETRY|CMD|arg1|arg2".

        Returns:
            TelemetryEvent или None если строка не является телеметрией.
        """
        if not msg.startswith("TELEMETRY|"):
            return None

        parts = msg.split("|")
        if len(parts) < 2:
            return None

        cmd = parts[1]

        if cmd == "PAGE_START" and len(parts) >= 3:
            try:
                return cls(
                    event_type=TelemetryEventType.PAGE_START,
                    page_number=int(parts[2]),
                )
            except ValueError:
                return None

        if cmd == "PROGRESS" and len(parts) >= 5:
            try:
                return cls(
                    event_type=TelemetryEventType.PROGRESS,
                    branch_url=parts[2],
                    current=int(parts[3]),
                    total=int(parts[4]),
                )
            except ValueError:
                return None

        if cmd == "BRANCH_DONE" and len(parts) >= 4:
            try:
                return cls(
                    event_type=TelemetryEventType.BRANCH_DONE,
                    branch_url=parts[2],
                    current=int(parts[3]),
                )
            except ValueError:
                return None

        if cmd == "CAPTCHA" and len(parts) >= 3:
            state = parts[2]
            if state == "WAITING" and len(parts) >= 4:
                try:
                    return cls(
                        event_type=TelemetryEventType.CAPTCHA_WAITING,
                        seconds_remaining=int(parts[3]),
                    )
                except ValueError:
                    return None
            if state == "SOLVED":
                return cls(event_type=TelemetryEventType.CAPTCHA_SOLVED)

        return None
