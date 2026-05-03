from core.telemetry import TelemetryEvent, TelemetryEventType


class TestFromLogMessage:
    def test_non_telemetry_message_returns_none(self):
        assert TelemetryEvent.from_log_message("INFO: Something happened") is None

    def test_empty_string_returns_none(self):
        assert TelemetryEvent.from_log_message("") is None

    def test_telemetry_prefix_only_returns_none(self):
        assert TelemetryEvent.from_log_message("TELEMETRY|") is None

    def test_page_start(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PAGE_START|3")
        assert event is not None
        assert event.event_type == TelemetryEventType.PAGE_START
        assert event.page_number == 3

    def test_page_start_invalid_number(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PAGE_START|abc")
        assert event is None

    def test_page_start_missing_page(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PAGE_START")
        assert event is None

    def test_progress(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PROGRESS|/reviews|15|50")
        assert event is not None
        assert event.event_type == TelemetryEventType.PROGRESS
        assert event.branch_url == "/reviews"
        assert event.current == 15
        assert event.total == 50

    def test_progress_invalid_number(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PROGRESS|/url|abc|10")
        assert event is None

    def test_progress_missing_fields(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PROGRESS|/url|5")
        assert event is None

    def test_branch_done(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|BRANCH_DONE|/reviews|42")
        assert event is not None
        assert event.event_type == TelemetryEventType.BRANCH_DONE
        assert event.branch_url == "/reviews"
        assert event.current == 42

    def test_branch_done_invalid_number(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|BRANCH_DONE|/url|abc")
        assert event is None

    def test_branch_done_missing_fields(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|BRANCH_DONE|/url")
        assert event is None

    def test_captcha_waiting(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|WAITING|120")
        assert event is not None
        assert event.event_type == TelemetryEventType.CAPTCHA_WAITING
        assert event.seconds_remaining == 120

    def test_captcha_waiting_invalid_seconds(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|WAITING|abc")
        assert event is None

    def test_captcha_waiting_missing_seconds(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|WAITING")
        assert event is None

    def test_captcha_solved(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|SOLVED")
        assert event is not None
        assert event.event_type == TelemetryEventType.CAPTCHA_SOLVED

    def test_unknown_command_returns_none(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|UNKNOWN|data")
        assert event is None


class TestTelemetryEventType:
    def test_all_values(self):
        expected = {
            "page_start", "progress", "branch_done",
            "captcha_waiting", "captcha_solved",
            "worker_done", "worker_error",
        }
        actual = {e.value for e in TelemetryEventType}
        assert actual == expected
