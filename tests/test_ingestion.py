"""
PROMPT: Generate tests for standalone ingest_event_batch function covering success, idempotency, and batch processing.

CHANGES MADE: None (AI-generated tests for ingestion function).
"""

import pytest
from app.database import get_database, init_database
from app.ingestion import ingest_event_batch


class TestIngestionFunction:
    def test_ingest_batch_success(self, temp_db):
        events = [{
            "event_id": "550e8400-e29b-41d4-a716-446655449999",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_ingest_fn",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T11:00:00Z",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.9,
        }]
        accepted, rejected, errors = ingest_event_batch(events)
        assert accepted == 1
        assert rejected == 0
        assert errors == []

    def test_ingest_idempotent(self, temp_db):
        events = [{
            "event_id": "550e8400-e29b-41d4-a716-446655448888",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_idem_fn",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T11:00:00Z",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.9,
        }]
        accepted1, _, _ = ingest_event_batch(events)
        assert accepted1 == 1
        accepted2, _, _ = ingest_event_batch(events)
        assert accepted2 == 0  # Idempotent

    def test_ingest_multiple_events(self, temp_db):
        events = []
        for i in range(3):
            events.append({
                "event_id": f"550e8400-e29b-41d4-a716-44665544{i:04d}",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_MAIN_01",
                "visitor_id": f"VIS_batch_{i}",
                "event_type": "ZONE_ENTER",
                "timestamp": f"2026-04-10T11:{10+i}:00Z",
                "zone_id": "BROWSING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.8,
            })
        accepted, rejected, errors = ingest_event_batch(events)
        assert accepted == 3
        assert rejected == 0
