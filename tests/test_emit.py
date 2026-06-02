"""
PROMPT: Generate tests for pipeline event emission helpers covering all event types and JSONL I/O.

CHANGES MADE: None (AI-generated tests for emit module).
"""

from datetime import datetime, timezone

import pytest
from pipeline.emit import (
    emit_event,
    emit_entry,
    emit_exit,
    emit_zone_enter,
    emit_zone_exit,
    emit_zone_dwell,
    emit_billing_queue_join,
    emit_billing_queue_abandon,
    emit_reentry,
    events_to_jsonl,
    events_from_jsonl,
)


class TestEmitEvent:
    def test_emit_event_creates_valid_structure(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_event(
            "STORE_BLR_002", "CAM_ENTRY_01", "VIS_test001", "ENTRY", ts
        )
        assert event["store_id"] == "STORE_BLR_002"
        assert event["camera_id"] == "CAM_ENTRY_01"
        assert event["visitor_id"] == "VIS_test001"
        assert event["event_type"] == "ENTRY"
        assert event["timestamp"] == "2026-04-10T11:00:00Z"
        assert "event_id" in event
        assert len(event["event_id"]) == 36  # UUID v4 format

    def test_emit_event_with_zone_and_dwell(self):
        ts = datetime(2026, 4, 10, 11, 5, 0, tzinfo=timezone.utc)
        event = emit_event(
            "STORE_BLR_002", "CAM_MAIN_01", "VIS_test001",
            "ZONE_DWELL", ts, zone_id="BROWSING",
            dwell_ms=5000, confidence=0.85, sku_zone="A1", session_seq=2,
        )
        assert event["zone_id"] == "BROWSING"
        assert event["dwell_ms"] == 5000
        assert event["confidence"] == 0.85
        assert event["metadata"]["sku_zone"] == "A1"
        assert event["metadata"]["session_seq"] == 2

    def test_invalid_event_type_raises(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Invalid event_type"):
            emit_event("S", "C", "V", "INVALID", ts)


class TestEmitShorthands:
    def test_emit_entry(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_entry("STORE_BLR_002", "CAM_ENTRY_01", "VIS_test001", ts)
        assert event["event_type"] == "ENTRY"
        assert event["confidence"] == 0.9

    def test_emit_exit(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_exit("STORE_BLR_002", "CAM_ENTRY_01", "VIS_test001", ts)
        assert event["event_type"] == "EXIT"

    def test_emit_zone_enter(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_zone_enter(
            "STORE_BLR_002", "CAM_MAIN_01", "VIS_test001", ts, "BROWSING"
        )
        assert event["event_type"] == "ZONE_ENTER"
        assert event["zone_id"] == "BROWSING"

    def test_emit_zone_exit(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_zone_exit(
            "STORE_BLR_002", "CAM_MAIN_01", "VIS_test001", ts, "BROWSING"
        )
        assert event["event_type"] == "ZONE_EXIT"
        assert event["zone_id"] == "BROWSING"

    def test_emit_zone_dwell(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_zone_dwell(
            "STORE_BLR_002", "CAM_MAIN_01", "VIS_test001",
            ts, "SKINCARE", 8000, sku_zone="B2",
        )
        assert event["event_type"] == "ZONE_DWELL"
        assert event["dwell_ms"] == 8000
        assert event["zone_id"] == "SKINCARE"
        assert event["metadata"]["sku_zone"] == "B2"

    def test_emit_billing_queue_join(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_billing_queue_join(
            "STORE_BLR_002", "CAM_BILLING_01", "VIS_test001", ts, 3
        )
        assert event["event_type"] == "BILLING_QUEUE_JOIN"
        assert event["metadata"]["queue_depth"] == 3
        assert event["zone_id"] == "BILLING"

    def test_emit_billing_queue_abandon(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_billing_queue_abandon(
            "STORE_BLR_002", "CAM_BILLING_01", "VIS_test001", ts
        )
        assert event["event_type"] == "BILLING_QUEUE_ABANDON"

    def test_emit_reentry(self):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        event = emit_reentry(
            "STORE_BLR_002", "CAM_ENTRY_01", "VIS_test001", ts
        )
        assert event["event_type"] == "REENTRY"
        assert event["confidence"] == 0.7


class TestJsonlRoundTrip:
    def test_events_to_jsonl_and_from_jsonl(self, tmp_path):
        ts = datetime(2026, 4, 10, 11, 0, 0, tzinfo=timezone.utc)
        events = [
            emit_entry("S", "C", "V1", ts),
            emit_exit("S", "C", "V1", ts),
            emit_zone_enter("S", "C", "V2", ts, "BROWSING"),
        ]
        fp = str(tmp_path / "events.jsonl")
        events_to_jsonl(events, fp)
        loaded = events_from_jsonl(fp)
        assert len(loaded) == 3
        assert loaded[0]["event_type"] == "ENTRY"
        assert loaded[1]["event_type"] == "EXIT"
        assert loaded[2]["event_type"] == "ZONE_ENTER"
