from core.telemetry import TelemetryEvent, TelemetryEventType


class TestTelemetryEventType:
    def test_enum_values(self):
        assert TelemetryEventType.PAGE_START.value == "page_start"
        assert TelemetryEventType.PROGRESS.value == "progress"
        assert TelemetryEventType.BRANCH_DONE.value == "branch_done"
        assert TelemetryEventType.CAPTCHA_WAITING.value == "captcha_waiting"
        assert TelemetryEventType.CAPTCHA_SOLVED.value == "captcha_solved"
        assert TelemetryEventType.WORKER_DONE.value == "worker_done"
        assert TelemetryEventType.WORKER_ERROR.value == "worker_error"


class TestTelemetryEvent:
    def test_from_log_message_not_telemetry(self):
        assert TelemetryEvent.from_log_message("some random log") is None

    def test_from_log_message_empty(self):
        assert TelemetryEvent.from_log_message("") is None

    def test_from_log_message_prefix_only(self):
        assert TelemetryEvent.from_log_message("TELEMETRY|") is None

    def test_from_log_page_start(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PAGE_START|5")
        assert event is not None
        assert event.event_type == TelemetryEventType.PAGE_START
        assert event.page_number == 5

    def test_from_log_page_start_invalid_number(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PAGE_START|abc")
        assert event is None

    def test_from_log_page_start_missing_page(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PAGE_START")
        assert event is None

    def test_from_log_progress(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PROGRESS|https://example.com|10|50")
        assert event is not None
        assert event.event_type == TelemetryEventType.PROGRESS
        assert event.branch_url == "https://example.com"
        assert event.current == 10
        assert event.total == 50

    def test_from_log_progress_invalid_numbers(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PROGRESS|url|abc|50")
        assert event is None

    def test_from_log_progress_missing_args(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|PROGRESS|url|10")
        assert event is None

    def test_from_log_branch_done(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|BRANCH_DONE|https://example.com|25")
        assert event is not None
        assert event.event_type == TelemetryEventType.BRANCH_DONE
        assert event.branch_url == "https://example.com"
        assert event.current == 25

    def test_from_log_branch_done_invalid(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|BRANCH_DONE|url|abc")
        assert event is None

    def test_from_log_branch_done_missing(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|BRANCH_DONE|url")
        assert event is None

    def test_from_log_captcha_waiting(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|WAITING|120")
        assert event is not None
        assert event.event_type == TelemetryEventType.CAPTCHA_WAITING
        assert event.seconds_remaining == 120

    def test_from_log_captcha_waiting_invalid(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|WAITING|abc")
        assert event is None

    def test_from_log_captcha_waiting_missing(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|WAITING")
        assert event is None

    def test_from_log_captcha_solved(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|CAPTCHA|SOLVED")
        assert event is not None
        assert event.event_type == TelemetryEventType.CAPTCHA_SOLVED

    def test_from_log_unknown_cmd(self):
        event = TelemetryEvent.from_log_message("TELEMETRY|UNKNOWN|data")
        assert event is None

    def test_event_defaults(self):
        event = TelemetryEvent(event_type=TelemetryEventType.PAGE_START)
        assert event.spec_name == ""
        assert event.page_number is None
        assert event.branch_url is None
        assert event.current is None
        assert event.total is None
        assert event.seconds_remaining is None
        assert event.error_message is None
