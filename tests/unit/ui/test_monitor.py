from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from core.resources import SystemStats
from core.telemetry import TelemetryEvent, TelemetryEventType
from ui.pages.monitor import MonitorPage, _records_label


@pytest.fixture()
def mock_ctrl() -> MagicMock:
    ctrl = MagicMock()
    ctrl.theme = MagicMock()
    ctrl.theme.tokens = MagicMock()
    ctrl.theme.tokens.accent = "#22C55E"
    ctrl.theme.tokens.accent_danger = "#EF4444"
    ctrl.theme.tokens.accent_warn = "#F59E0B"
    ctrl.theme.tokens.accent_info = "#3B82F6"
    ctrl.theme.tokens.text_primary = "#FFFFFF"
    ctrl.theme.tokens.text_secondary = "#A1A1AA"
    ctrl.theme.tokens.text_muted = "#52525B"
    ctrl.theme.tokens.bg_primary = "#0F0F0F"
    ctrl.theme.tokens.bg_secondary = "#1A1A1A"
    ctrl.theme.tokens.bg_elevated = "#242424"
    ctrl.theme.tokens.border = "#27272A"
    ctrl.is_running.return_value = False
    ctrl.active_specs = ["reddit.yaml"]
    ctrl._ui_log_handler = None
    ctrl.log_manager = MagicMock()
    ctrl.log_manager.add_handler.return_value = True
    ctrl.page = MagicMock()
    return ctrl


class TestRecordsLabel:
    def test_habr_label(self) -> None:
        assert "статей" in _records_label("habr_articles", 5)

    def test_reddit_label(self) -> None:
        assert "комментариев" in _records_label("reddit_discussions", 10)

    def test_steam_label(self) -> None:
        assert "отзывов" in _records_label("steam_reviews", 3)

    def test_unknown_label(self) -> None:
        assert "записей" in _records_label("unknown_source", 1)


class TestMonitorPageBuild:
    def test_build_returns_control(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        control = page.build()
        assert control is not None


class TestMonitorStartMonitoring:
    def test_start_monitoring_resets_state(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        with patch("threading.Thread"):
            page.start_monitoring()
        assert page._is_monitoring is True
        assert page._stop_btn.visible is True


class TestMonitorTelemetry:
    @pytest.mark.asyncio
    async def test_apply_telemetry_page_start(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        event = TelemetryEvent(event_type=TelemetryEventType.PAGE_START, page_number=3)
        await page._apply_telemetry(event)
        assert "3" in page._status_text.value
        mock_ctrl.page.update.assert_called()

    @pytest.mark.asyncio
    async def test_apply_telemetry_captcha_waiting(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        event = TelemetryEvent(event_type=TelemetryEventType.CAPTCHA_WAITING, seconds_remaining=30)
        await page._apply_telemetry(event)
        assert "30" in page._status_text.value

    @pytest.mark.asyncio
    async def test_apply_telemetry_captcha_solved(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        event = TelemetryEvent(event_type=TelemetryEventType.CAPTCHA_SOLVED)
        await page._apply_telemetry(event)
        assert "пройдена" in page._status_text.value

    @pytest.mark.asyncio
    async def test_apply_telemetry_progress(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        event = TelemetryEvent(
            event_type=TelemetryEventType.PROGRESS,
            branch_url="https://example.com/page",
            current=10,
            total=50,
        )
        await page._apply_telemetry(event)
        mock_ctrl.page.update.assert_called()

    @pytest.mark.asyncio
    async def test_apply_telemetry_branch_done(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        event = TelemetryEvent(
            event_type=TelemetryEventType.BRANCH_DONE,
            branch_url="https://example.com/reviews",
            current=25,
        )
        await page._apply_telemetry(event)
        assert page._total_records == 25


class TestMonitorBranchName:
    def test_branch_name_from_url(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        name = page._branch_name("https://example.com/reviews/12345")
        assert name

    def test_branch_name_short_url(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        name = page._branch_name("reviews")
        assert name


class TestMonitorAddLogLine:
    @pytest.mark.asyncio
    async def test_add_log_line(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test message", args=(), exc_info=None,
        )
        await page._add_log_line(record)
        assert len(page._log_col.controls) == 1

    @pytest.mark.asyncio
    async def test_add_log_line_truncates_at_max(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        page.MAX_LOG_LINES = 3
        for i in range(5):
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg=f"Msg {i}", args=(), exc_info=None,
            )
            await page._add_log_line(record)
        assert len(page._log_col.controls) == 3


class TestMonitorOnStop:
    def test_on_stop(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        page._is_monitoring = True
        mock_event = MagicMock()
        page._on_stop(mock_event)
        assert page._is_monitoring is False
        assert page._stop_btn.visible is False
        mock_ctrl.stop_parsing.assert_called_once()


class TestMonitorResources:
    @pytest.mark.asyncio
    async def test_update_resources_ui(self, mock_ctrl: MagicMock) -> None:
        page = MonitorPage(mock_ctrl)
        page.build()
        stats = SystemStats(cpu_percent=50.0, ram_percent=60.0, ram_used_gb=8.0, ram_total_gb=16.0, app_memory_mb=256.0)
        await page._update_resources_ui(stats)
        mock_ctrl.page.update.assert_called()
