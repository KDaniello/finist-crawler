import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["ProfileManager", "SessionConfig", "SessionHealth", "SessionState", "SessionStats"]


class SessionHealth(Enum):
    NEW = "new"  # Только создан
    WARM = "warm"  # Прогрет, готов к бою
    ACTIVE = "active"  # В работе прямо сейчас
    IDLE = "idle"  # Свободен
    COOLDOWN = "cooldown"  # Отдыхает после 429
    BANNED = "banned"  # Забанен Cloudflare
    EXPIRED = "expired"  # Превысил лимит запросов


@dataclass
class SessionConfig:
    """Лимиты жизни профиля браузера."""

    max_requests: int = 500
    max_age_seconds: float = 86400.0  # 24 часа
    max_errors: int = 20
    max_consecutive_errors: int = 5
    cooldown_seconds: float = 300.0  # 5 минут отдыха при 429
    warmup_required: bool = True


@dataclass
class SessionStats:
    """Метрики успешности профиля."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    captchas: int = 0
    consecutive_errors: int = 0

    created_at: float = field(default_factory=time.time)
    last_used_at: float = 0.0
    cooldown_until: float = 0.0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def is_on_cooldown(self) -> bool:
        return time.time() < self.cooldown_until


@dataclass
class SessionState:
    """Полное состояние браузерной сессии."""

    domain: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    health: SessionHealth = SessionHealth.NEW
    config: SessionConfig = field(default_factory=SessionConfig)
    stats: SessionStats = field(default_factory=SessionStats)

    @property
    def is_expired(self) -> bool:
        if self.stats.total_requests >= self.config.max_requests:
            return True
        if self.stats.age_seconds >= self.config.max_age_seconds:
            return True
        if self.stats.failed_requests >= self.config.max_errors:
            return True
        return False

    @property
    def should_rotate(self) -> bool:
        if self.health in (SessionHealth.BANNED, SessionHealth.EXPIRED):
            return True
        if self.is_expired:
            return True
        if self.stats.consecutive_errors >= self.config.max_consecutive_errors:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "session_id": self.session_id,
            "health": self.health.value,
            "config": asdict(self.config),
            "stats": asdict(self.stats),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        config_data = data.get("config", {})
        stats_data = data.get("stats", {})

        return cls(
            domain=data["domain"],
            session_id=data.get("session_id") or uuid.uuid4().hex[:12],
            health=SessionHealth(data.get("health", "new")),
            config=SessionConfig(**config_data) if config_data else SessionConfig(),
            stats=SessionStats(**stats_data) if stats_data else SessionStats(),
        )


class ProfileManager:
    """
    Управляет жизненным циклом профилей браузера через JSON-файлы на диске.
    Заменяет собой SessionPool + SessionStorage (SQLAlchemy) из энтерпрайза.
    """

    def __init__(self, domain: str, base_profiles_dir: Path) -> None:
        self.domain = domain
        # Все сессии домена лежат в: data/profiles/reddit.com/
        self.domain_dir = base_profiles_dir / domain
        self.domain_dir.mkdir(parents=True, exist_ok=True)

    def _get_state_path(self, session_id: str) -> Path:
        """Путь к JSON файлу метаданных конкретной сессии."""
        session_dir = self.domain_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "state.json"

    def save(self, session: SessionState) -> None:
        """Атомарное сохранение состояния на диск."""
        path = self._get_state_path(session.session_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2)
            logger.debug(
                f"[ProfileManager] Сохранен стейт {session.session_id} -> {session.health.value}"
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения стейта профиля {session.session_id}: {e}")

    def acquire(self) -> SessionState:
        """
        Ищет на диске лучший живой профиль (IDLE/WARM).
        Если все забанены или на кулдауне — создает новый.
        """
        candidates: list[SessionState] = []

        # Сканируем все папки сессий внутри домена
        for session_dir in self.domain_dir.iterdir():
            if not session_dir.is_dir():
                continue

            state_file = session_dir / "state.json"
            if not state_file.exists():
                continue

            try:
                with open(state_file, encoding="utf-8") as f:
                    data = json.load(f)
                session = SessionState.from_dict(data)

                # Реанимация после кулдауна
                if session.health == SessionHealth.COOLDOWN and not session.stats.is_on_cooldown:
                    session.health = SessionHealth.IDLE

                if session.health in (SessionHealth.BANNED, SessionHealth.EXPIRED):
                    continue

                if session.is_expired or session.should_rotate:
                    session.health = SessionHealth.EXPIRED
                    self.save(session)
                    continue

                if session.health in (SessionHealth.IDLE, SessionHealth.WARM, SessionHealth.NEW):
                    candidates.append(session)
            except Exception as e:
                logger.warning(f"Поврежден файл профиля {session_dir.name}: {e}")

        # Выбираем самый "опытный" (но живой) профиль с наибольшим числом успехов
        if candidates:
            best_session = sorted(
                candidates, key=lambda s: s.stats.successful_requests, reverse=True
            )[0]
            best_session.health = SessionHealth.ACTIVE
            best_session.stats.last_used_at = time.time()
            self.save(best_session)
            logger.info(
                f"[ProfileManager] Выбран профиль {best_session.session_id} (reqs: {best_session.stats.total_requests})"
            )
            return best_session

        # Если живых нет — создаем новый
        new_session = SessionState(domain=self.domain, health=SessionHealth.ACTIVE)
        self.save(new_session)
        logger.info(f"[ProfileManager] Создан новый профиль {new_session.session_id}")
        return new_session

    def report_success(self, session: SessionState) -> None:
        session.stats.total_requests += 1
        session.stats.successful_requests += 1
        session.stats.consecutive_errors = 0
        self.save(session)

    def report_failure(
        self, session: SessionState, is_banned: bool = False, is_captcha: bool = False
    ) -> None:
        session.stats.total_requests += 1
        session.stats.failed_requests += 1
        session.stats.consecutive_errors += 1

        if is_banned:
            session.health = SessionHealth.BANNED
            logger.warning(f"[ProfileManager] Профиль {session.session_id} ЗАБАНЕН!")
        elif is_captcha:
            session.stats.captchas += 1
            session.health = SessionHealth.COOLDOWN
            session.stats.cooldown_until = time.time() + session.config.cooldown_seconds
            logger.warning(
                f"[ProfileManager] Профиль {session.session_id} поймал капчу. Отдых {session.config.cooldown_seconds}с."
            )

        self.save(session)

    def release(self, session: SessionState) -> None:
        """Освобождает профиль после работы парсера."""
        if session.health == SessionHealth.ACTIVE:
            session.health = SessionHealth.IDLE
        self.save(session)
