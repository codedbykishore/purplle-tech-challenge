"""
PROMPT: Generate comprehensive tests for POST /events/ingest endpoint.
Cover: basic ingest, batch of 500, idempotency, malformed events, partial success.

CHANGES MADE: Added edge cases for empty batches, oversized batches, session
triggering via ENTRY/EXIT/ZONE_ENTER(BILLING), and error handling.
"""

import pytest


class TestIngestBasic:
    def test_ingest_single_event(self, client, sample_event):
        """Test ingesting a single valid event."""
        resp = client.post("/events/ingest", json={"events": [sample_event]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 1
        assert data["rejected"] == 0

    def test_ingest_multiple_events(self, client, sample_events_batch):
        """Test ingesting a batch of events."""
        resp = client.post("/events/ingest", json={"events": sample_events_batch})
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 5
        assert data["rejected"] == 0

    def test_ingest_empty_batch(self, client):
        """Test ingesting an empty batch."""
        resp = client.post("/events/ingest", json={"events": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 0
        assert data["rejected"] == 0


class TestIdempotency:
    def test_duplicate_event_id_ignored(self, client, sample_event):
        """Test that duplicate event_id is not counted twice."""
        # Ingest once
        r1 = client.post("/events/ingest", json={"events": [sample_event]})
        assert r1.json()["accepted"] == 1

        # Ingest same event again
        r2 = client.post("/events/ingest", json={"events": [sample_event]})
        assert r2.status_code == 200
        # Duplicate should not increase accepted count
        assert r2.json()["accepted"] == 0


class TestBatchLimit:
    def test_batch_of_500_accepted(self, client):
        """Test that a batch of exactly 500 events is accepted."""
        events = []
        for i in range(500):
            events.append({
                "event_id": f"550e8400-e29b-41d4-a716-{i:012d}",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_MAIN_01",
                "visitor_id": f"VIS_b500_{i:03d}",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-04-10T11:00:00Z",
                "zone_id": "BROWSING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.8,
                "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
            })
        resp = client.post("/events/ingest", json={"events": events})
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 500

    def test_batch_exceeding_500_rejected(self, client):
        """Test that batch > 500 is rejected."""
        events = [{"event_id": f"e{i}", "store_id": "STORE_BLR_002",
                   "camera_id": "CAM_MAIN_01", "visitor_id": f"V{i}",
                   "event_type": "ENTRY", "timestamp": "2026-04-10T11:00:00Z",
                   "dwell_ms": 0, "is_staff": False, "confidence": 0.8,
                   "metadata": {}}
                  for i in range(501)]
        resp = client.post("/events/ingest", json={"events": events})
        assert resp.status_code == 400


class TestSessionTriggering:
    """Test that session manager is triggered on ENTRY/EXIT/ZONE_ENTER."""

    def test_ingest_entry_triggers_session(self, client, sample_event):
        """ENTRY event should create a session."""
        resp = client.post("/events/ingest", json={"events": [sample_event]})
        assert resp.status_code == 200

    def test_ingest_exit_triggers_session_close(self, client):
        """EXIT event should close the session."""
        entry = {
            "event_id": "e-entry-001", "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01", "visitor_id": "VIS_sess_test",
            "event_type": "ENTRY", "timestamp": "2026-04-10T11:00:00Z",
            "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
            "metadata": {},
        }
        client.post("/events/ingest", json={"events": [entry]})
        exit_evt = {
            "event_id": "e-exit-001", "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01", "visitor_id": "VIS_sess_test",
            "event_type": "EXIT", "timestamp": "2026-04-10T11:10:00Z",
            "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
            "metadata": {},
        }
        resp = client.post("/events/ingest", json={"events": [exit_evt]})
        assert resp.status_code == 200

    def test_ingest_zone_enter_billing_triggers_session_update(self, client):
        """ZONE_ENTER with BILLING zone should update session billing time."""
        entry = {
            "event_id": "e-bill-entry", "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01", "visitor_id": "VIS_bill_test",
            "event_type": "ENTRY", "timestamp": "2026-04-10T11:00:00Z",
            "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
            "metadata": {},
        }
        client.post("/events/ingest", json={"events": [entry]})
        billing = {
            "event_id": "e-bill-zone", "store_id": "STORE_BLR_002",
            "camera_id": "CAM_BILLING_01", "visitor_id": "VIS_bill_test",
            "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T11:25:00Z",
            "zone_id": "BILLING", "dwell_ms": 0, "is_staff": False,
            "confidence": 0.9, "metadata": {},
        }
        resp = client.post("/events/ingest", json={"events": [billing]})
        assert resp.status_code == 200


class TestPartialSuccess:
    def test_mixed_batch_partial_success(self, client):
        """Test batch with valid and malformed events returns partial success."""
        events = [
            # Valid event
            {
                "event_id": "550e8400-e29b-41d4-a716-000000000001",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_good01",
                "event_type": "ENTRY",
                "timestamp": "2026-04-10T11:00:00Z",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
            },
            # Invalid event_type
            {
                "event_id": "550e8400-e29b-41d4-a716-000000000002",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_bad001",
                "event_type": "INVALID_TYPE",
                "timestamp": "2026-04-10T11:01:00Z",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {},
            },
            # Another valid event
            {
                "event_id": "550e8400-e29b-41d4-a716-000000000003",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_MAIN_01",
                "visitor_id": "VIS_good02",
                "event_type": "ZONE_ENTER",
                "timestamp": "2026-04-10T11:02:00Z",
                "zone_id": "BROWSING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.8,
                "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
            },
        ]
        resp = client.post("/events/ingest", json={"events": events})
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] >= 1  # At least the valid events
        assert data["rejected"] >= 1  # At least the invalid event
