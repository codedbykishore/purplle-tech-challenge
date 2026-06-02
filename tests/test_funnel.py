"""
PROMPT: Generate tests for GET /stores/{id}/funnel covering stage structure, zero-data edge cases, and dropoff calculations.

CHANGES MADE: None (AI-generated tests for funnel).
"""

import pytest


class TestFunnel:
    def test_funnel_returns_200(self, client):
        resp = client.get("/stores/STORE_BLR_002/funnel")
        assert resp.status_code == 200

    def test_funnel_has_stages(self, client):
        resp = client.get("/stores/STORE_BLR_002/funnel")
        data = resp.json()
        assert "stages" in data
        assert len(data["stages"]) == 4
        stage_names = [s["name"] for s in data["stages"]]
        assert "Entry" in stage_names
        assert "Purchase" in stage_names

    def test_funnel_zero_purchase_no_crash(self, client):
        """Test funnel for store with no events doesn't crash."""
        resp = client.get("/stores/STORE_ZERO/funnel")
        assert resp.status_code < 500  # No 5xx

    def test_funnel_with_entry_data(self, client):
        """Test funnel counts increase when events are ingested."""
        # Ingest 3 ENTRY events
        events = []
        for i in range(3):
            events.append({
                "event_id": f"550e8400-e29b-41d4-a716-fun{i:08d}",
                "store_id": "STORE_BLR_002", "camera_id": "CAM_ENTRY_01",
                "visitor_id": f"VIS_fun{i:03d}", "event_type": "ENTRY",
                "timestamp": f"2026-04-10T11:0{i}:00Z",
                "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
                "metadata": {},
            })
        client.post("/events/ingest", json={"events": events})
        resp = client.get("/stores/STORE_BLR_002/funnel")
        data = resp.json()
        entry_stage = [s for s in data["stages"] if s["name"] == "Entry"]
        assert len(entry_stage) == 1
        assert entry_stage[0]["count"] == 3

    def test_funnel_with_zone_visits(self, client):
        """Test funnel counts zone visits."""
        entry = {
            "event_id": "550e8400-e29b-41d4-a716-fzzz00000001",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_zone_funnel", "event_type": "ENTRY",
            "timestamp": "2026-04-10T11:00:00Z",
            "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
            "metadata": {},
        }
        zone = {
            "event_id": "550e8400-e29b-41d4-a716-fzzz00000002",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_MAIN_01",
            "visitor_id": "VIS_zone_funnel", "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T11:05:00Z",
            "zone_id": "SKINCARE", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.8,
            "metadata": {},
        }
        client.post("/events/ingest", json={"events": [entry, zone]})
        resp = client.get("/stores/STORE_BLR_002/funnel")
        data = resp.json()
        zone_stage = [s for s in data["stages"] if s["name"] == "Zone Visit"]
        assert len(zone_stage) == 1
        assert zone_stage[0]["count"] >= 1
