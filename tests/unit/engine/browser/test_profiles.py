"""
Тесты для engine/browser/profiles.py

Покрытие: 100%
- SessionStats: вычисление возраста и статуса кулдауна.
- SessionState:
    - Проверка is_expired (по запросам, по времени, по ошибкам).
    - Проверка should_rotate (состояние banned/expired, серия ошибок).
    - Сериализация и десериализация (to_dict / from_dict).
- ProfileManager:
    - Создание структуры папок при инициализации.
    - save: успешное сохранение в JSON и обработка ошибок записи (Read Only FS).
    - acquire:
        - Игнорирование не-папок и пустых папок.
        - Игнорирование битых JSON файлов.
        - Выбор лучшего живого профиля (сортировка по успешным запросам).
        - Истечение срока жизни (EXPIRED) при сканировании.
        - Реанимация профиля после кулдауна.
        - Игнорирование забаненных профилей.
        - Создание нового профиля, если живых нет.
    - report_success: сброс счетчика ошибок подряд, инкремент успешных запросов.
    - report_failure:
        - Обычная ошибка (инкремент failed/consecutive).
        - Капча (перевод в COOLDOWN, установка таймера).
        - Бан (перевод в BANNED).
    - release: перевод из ACTIVE в IDLE.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.browser.profiles import (
    ProfileManager,
    SessionConfig,
    SessionHealth,
    SessionState,
    SessionStats,
)

# ---------------------------------------------------------------------------
# SessionStats & SessionState Logic Tests
# ---------------------------------------------------------------------------


class TestSessionModels:
    @patch("time.time")
    def test_stats_properties(self, mock_time):
        mock_time.return_value = 100.0

        stats = SessionStats(created_at=50.0, cooldown_until=150.0)
        assert stats.age_seconds == 50.0
        assert stats.is_on_cooldown is True

        stats.cooldown_until = 90.0
        assert stats.is_on_cooldown is False

    def test_state_is_expired(self):
        state = SessionState("test.com", config=SessionConfig(max_requests=10, max_errors=2))

        # Лимит запросов
        state.stats.total_requests = 10
        assert state.is_expired is True

        state.stats.total_requests = 5
        # Лимит ошибок
        state.stats.failed_requests = 2
        assert state.is_expired is True

    @patch("time.time", return_value=100000.0)
    def test_state_is_expired_by_age(self, mock_time):
        state = SessionState(
            "test.com",
            stats=SessionStats(created_at=10.0),
            config=SessionConfig(max_age_seconds=100.0),
        )
        assert state.is_expired is True

    def test_should_rotate(self):
        state = SessionState("test.com", config=SessionConfig(max_consecutive_errors=3))

        # Смертельные статусы
        state.health = SessionHealth.BANNED
        assert state.should_rotate is True

        state.health = SessionHealth.IDLE
        # Истек по лимитам (is_expired)
        state.stats.total_requests = 9999
        assert state.should_rotate is True

        state.stats.total_requests = 0
        # Серия ошибок
        state.stats.consecutive_errors = 3
        assert state.should_rotate is True

        state.stats.consecutive_errors = 0
        assert state.should_rotate is False

    def test_serialization(self):
        state1 = SessionState("test.com", health=SessionHealth.IDLE)
        state1.stats.successful_requests = 5

        data = state1.to_dict()
        state2 = SessionState.from_dict(data)

        assert state2.domain == "test.com"
        assert state2.session_id == state1.session_id
        assert state2.health == SessionHealth.IDLE
        assert state2.stats.successful_requests == 5

    def test_from_dict_defaults(self):
        """Если в JSON нет id, config или stats, они создаются по дефолту."""
        state = SessionState.from_dict({"domain": "test.com"})

        assert state.session_id is not None
        assert state.config.max_requests == 500
        assert state.stats.total_requests == 0


# ---------------------------------------------------------------------------
# ProfileManager Tests
# ---------------------------------------------------------------------------


class TestProfileManager:
    @pytest.fixture
    def manager(self, tmp_path: Path):
        return ProfileManager("reddit.com", tmp_path)

    def test_init_creates_dir(self, tmp_path: Path):
        ProfileManager("test.com", tmp_path)
        assert (tmp_path / "test.com").exists()

    def test_save_success(self, manager):
        state = SessionState("reddit.com", session_id="abc")
        manager.save(state)

        path = manager._get_state_path("abc")
        assert path.exists()

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["session_id"] == "abc"

    def test_save_error(self, manager, caplog):
        state = SessionState("reddit.com", session_id="abc")

        with patch("builtins.open", side_effect=OSError("Read Only")):
            manager.save(state)

        assert "Ошибка сохранения стейта профиля abc" in caplog.text

    def test_acquire_creates_new_if_empty(self, manager):
        """Если папка пуста, создается новый активный профиль."""
        session = manager.acquire()
        assert session.health == SessionHealth.ACTIVE
        assert manager._get_state_path(session.session_id).exists()

    def test_acquire_ignores_invalid_files(self, manager, tmp_path):
        """Игнорирует левые файлы, пустые папки и битый JSON."""
        # Не папка
        (manager.domain_dir / "file.txt").touch()

        # Пустая папка (без state.json)
        (manager.domain_dir / "empty_dir").mkdir()

        # Папка с битым JSON
        bad_dir = manager.domain_dir / "bad_json"
        bad_dir.mkdir()
        (bad_dir / "state.json").write_text("not json")

        # Так как живых нет, должен создать новый профиль
        session = manager.acquire()
        assert session.health == SessionHealth.ACTIVE

    def test_acquire_finds_best_profile(self, manager):
        """Среди нескольких живых выбирается тот, у кого больше успешных запросов."""
        s1 = SessionState("reddit.com", session_id="s1", health=SessionHealth.IDLE)
        s1.stats.successful_requests = 10
        manager.save(s1)

        s2 = SessionState("reddit.com", session_id="s2", health=SessionHealth.WARM)
        s2.stats.successful_requests = 50  # Лучший
        manager.save(s2)

        session = manager.acquire()
        assert session.session_id == "s2"
        assert session.health == SessionHealth.ACTIVE

    @patch("time.time", return_value=100.0)
    def test_acquire_cooldown_revival(self, mock_time, manager):
        """Профиль на кулдауне оживает, если время вышло."""
        s = SessionState("reddit.com", session_id="cooldown_profile", health=SessionHealth.COOLDOWN)
        s.stats.cooldown_until = 50.0  # Кулдаун уже прошел
        manager.save(s)

        session = manager.acquire()
        assert session.session_id == "cooldown_profile"
        assert session.health == SessionHealth.ACTIVE

    def test_acquire_expires_old_profiles(self, manager):
        """При сканировании профиль помечается как EXPIRED, если он отслужил свое."""
        s = SessionState("reddit.com", session_id="old_profile", health=SessionHealth.IDLE)
        s.stats.total_requests = 9999  # Истек по лимиту
        manager.save(s)

        session = manager.acquire()

        # Создастся новый, так как старый "умер"
        assert session.session_id != "old_profile"

        # Проверяем, что старый профиль на диске получил статус EXPIRED
        old_data = json.loads(manager._get_state_path("old_profile").read_text())
        assert old_data["health"] == "expired"

    def test_acquire_ignores_banned_profiles(self, manager):
        """Забаненные профили никогда не выбираются."""
        s = SessionState("reddit.com", session_id="banned_profile", health=SessionHealth.BANNED)
        manager.save(s)

        session = manager.acquire()
        assert session.session_id != "banned_profile"

    def test_report_success(self, manager):
        s = SessionState("reddit.com")
        s.stats.consecutive_errors = 3

        manager.report_success(s)

        assert s.stats.total_requests == 1
        assert s.stats.successful_requests == 1
        assert s.stats.consecutive_errors == 0  # Сброшено

    def test_report_failure_normal(self, manager):
        s = SessionState("reddit.com")
        manager.report_failure(s)

        assert s.stats.failed_requests == 1
        assert s.stats.consecutive_errors == 1
        assert s.health == SessionHealth.NEW

    def test_report_failure_banned(self, manager, caplog):
        s = SessionState("reddit.com")
        manager.report_failure(s, is_banned=True)

        assert s.health == SessionHealth.BANNED
        assert "ЗАБАНЕН" in caplog.text

    @patch("time.time", return_value=100.0)
    def test_report_failure_captcha(self, mock_time, manager, caplog):
        s = SessionState("reddit.com", config=SessionConfig(cooldown_seconds=300))
        manager.report_failure(s, is_captcha=True)

        assert s.health == SessionHealth.COOLDOWN
        assert s.stats.captchas == 1
        assert s.stats.cooldown_until == 400.0  # 100 + 300
        assert "поймал капчу. Отдых" in caplog.text

    def test_release(self, manager):
        """Освобождение активного профиля переводит его в IDLE."""
        s = SessionState("reddit.com", health=SessionHealth.ACTIVE)
        manager.release(s)
        assert s.health == SessionHealth.IDLE

        # Забаненный профиль не должен становиться IDLE
        s.health = SessionHealth.BANNED
        manager.release(s)
        assert s.health == SessionHealth.BANNED
