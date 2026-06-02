"""
PROMPT: Generate tests for GET /stores/{id}/heatmap covering zone data and confidence levels.

CHANGES MADE: None (AI-generated tests for heatmap).
"""

import pytest


class TestHeatmap:
    def test_heatmap_returns_200(self, client):
        resp = client.get("/stores/STORE_BLR_002/heatmap")
        assert resp.status_code == 200

    def test_heatmap_has_zones(self, client):
        resp = client.get("/stores/STORE_BLR_002/heatmap")
        data = resp.json()
        assert "zones" in data
        assert "data_confidence" in data

    def test_heatmap_with_zone_data(self, client):
        """Test heatmap returns zone data after ingesting zone events."""
        events = []
        for i in range(5):
            events.append({
                "event_id": f"550e8400-e29b-41d4-a716-hm{i:08d}",
                "store_id": "STORE_BLR_002", "camera_id": "CAM_MAIN_01",
                "visitor_id": f"VIS_hm{i:03d}", "event_type": "ZONE_ENTER",
                "timestamp": f"2026-04-10T11:0{i}:00Z",
                "zone_id": "SKINCARE", "dwell_ms": 0,
                "is_staff": False, "confidence": 0.8,
                "metadata": {},
            })
        client.post("/events/ingest", json={"events": events})
        resp = client.get("/stores/STORE_BLR_002/heatmap")
        data = resp.json()
        assert len(data["zones"]) > 0
        zone_ids = [z["zone_id"] for z in data["zones"]]
        assert "SKINCARE" in zone_ids
        skincare_zone = [z for z in data["zones"] if z["zone_id"] == "SKINCARE"][0]
        assert skincare_zone["visit_count"] == 5
        assert 0 <= skincare_zone["score"] <= 100

    def test_heatmap_confidence_low_for_few_visitors(self, client):
        """Test data_confidence is 'low' for fewer than 10 visitors."""
        event = {
            "event_id": "550e8400-e29b-41d4-a716-hm9900000001",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_MAIN_01",
            "visitor_id": "VIS_hm_only", "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T11:00:00Z",
            "zone_id": "MAKEUP", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.8,
            "metadata": {},
        }
        client.post("/events/ingest", json={"events": [event]})
        resp = client.get("/stores/STORE_BLR_002/heatmap")
        data = resp.json()
        assert data["data_confidence"] == "low"
