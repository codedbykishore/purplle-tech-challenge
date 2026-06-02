"""
PROMPT: Generate tests for SessionManager covering session lifecycle, re-entry detection, and POS conversion.

CHANGES MADE: None (AI-generated tests for session management).
"""

import pytest
from datetime import datetime, timedelta, timezone
from app.session import SessionManager


class TestSessionManager:
    def test_create_and_get_session(self):
        sm = SessionManager()
        event = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        session = sm.create_session("VIS_001", "STORE_BLR_002", event)
        assert session.visitor_id == "VIS_001"
        assert sm.get_session("VIS_001") is session

    def test_get_session_returns_none_for_unknown(self):
        sm = SessionManager()
        assert sm.get_session("VIS_UNKNOWN") is None

    def test_close_session(self):
        sm = SessionManager()
        entry = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry)
        exit_evt = {"timestamp": "2026-04-10T11:10:00Z"}
        sm.close_session("VIS_001", exit_evt)
        session = sm.get_session("VIS_001")
        assert session.exit_time is not None

    def test_close_session_unknown_visitor_does_not_raise(self):
        sm = SessionManager()
        sm.close_session("VIS_GHOST", {"timestamp": "2026-04-10T11:00:00Z"})

    def test_check_reentry_within_window(self):
        sm = SessionManager()
        entry1 = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry1)
        exit1 = {"timestamp": "2026-04-10T11:05:00Z"}
        sm.close_session("VIS_001", exit1)

        entry2 = {"timestamp": "2026-04-10T11:08:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry2)
        assert sm.check_reentry("VIS_001", datetime(2026, 4, 10, 11, 8, 0, tzinfo=timezone.utc)) is True

    def test_check_reentry_outside_window(self):
        sm = SessionManager()
        entry1 = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry1)
        exit1 = {"timestamp": "2026-04-10T11:05:00Z"}
        sm.close_session("VIS_001", exit1)

        entry2 = {"timestamp": "2026-04-10T11:20:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry2)
        assert sm.check_reentry("VIS_001", datetime(2026, 4, 10, 11, 20, 0, tzinfo=timezone.utc)) is False

    def test_check_reentry_no_prior_session(self):
        sm = SessionManager()
        assert sm.check_reentry("VIS_NEW", datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)) is False

    def test_update_billing_entry(self):
        sm = SessionManager()
        entry = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry)
        sm.update_billing_entry(
            "VIS_001", datetime(2026, 4, 10, 11, 15, 0, tzinfo=timezone.utc)
        )
        session = sm.get_session("VIS_001")
        assert session.billing_entry_time is not None

    def test_update_billing_entry_unknown_visitor_does_not_raise(self):
        sm = SessionManager()
        sm.update_billing_entry("VIS_GHOST", datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc))

    def test_is_converted_within_window(self):
        sm = SessionManager()
        entry = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry)
        sm.update_billing_entry(
            "VIS_001", datetime(2026, 4, 10, 11, 15, 0, tzinfo=timezone.utc)
        )
        txns = [{"timestamp": "2026-04-10T11:16:00Z"}]
        assert sm.is_converted("VIS_001", txns) is True

    def test_is_converted_no_billing_entry(self):
        sm = SessionManager()
        entry = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry)
        txns = [{"timestamp": "2026-04-10T11:16:00Z"}]
        assert sm.is_converted("VIS_001", txns) is False

    def test_is_converted_no_session(self):
        sm = SessionManager()
        txns = [{"timestamp": "2026-04-10T11:16:00Z"}]
        assert sm.is_converted("VIS_NONE", txns) is False

    def test_is_converted_outside_window(self):
        sm = SessionManager()
        entry = {"timestamp": "2026-04-10T11:00:00Z", "is_staff": False}
        sm.create_session("VIS_001", "STORE_BLR_002", entry)
        sm.update_billing_entry(
            "VIS_001", datetime(2026, 4, 10, 11, 00, 0, tzinfo=timezone.utc)
        )
        txns = [{"timestamp": "2026-04-10T11:10:00Z"}]  # 10 min later
        assert sm.is_converted("VIS_001", txns) is False
