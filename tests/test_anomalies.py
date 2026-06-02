"""
PROMPT: Generate tests for GET /stores/{id}/anomalies covering queue spike detection.

CHANGES MADE: None (AI-generated tests for anomaly detection).
"""

import pytest


class TestAnomalies:
    def test_anomalies_returns_200(self, client):
        resp = client.get("/stores/STORE_BLR_002/anomalies")
        assert resp.status_code == 200

    def test_anomalies_is_list(self, client):
        resp = client.get("/stores/STORE_BLR_002/anomalies")
        data = resp.json()
        assert "anomalies" in data
        assert isinstance(data["anomalies"], list)

    def test_billing_queue_spike_anomaly(self, client):
        """Test billing queue spike detection (>6 queue depth)."""
        event = {
            "event_id": "550e8400-e29b-41d4-a716-aaa000000001",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_BILLING_01",
            "visitor_id": "VIS_anom_queue", "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-04-10T11:00:00Z",
            "zone_id": "BILLING", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.9,
            "metadata": {"queue_depth": 10},
        }
        client.post("/events/ingest", json={"events": [event]})
        resp = client.get("/stores/STORE_BLR_002/anomalies")
        data = resp.json()
        types = [a["type"] for a in data["anomalies"]]
        assert "BILLING_QUEUE_SPIKE" in types

    def test_no_queue_spike_for_normal_depth(self, client):
        """Test no billing queue spike for normal queue depth."""
        event = {
            "event_id": "550e8400-e29b-41d4-a716-aaa000000002",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_BILLING_01",
            "visitor_id": "VIS_anom_normal", "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-04-10T11:00:00Z",
            "zone_id": "BILLING", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.9,
            "metadata": {"queue_depth": 3},
        }
        client.post("/events/ingest", json={"events": [event]})
        resp = client.get("/stores/STORE_BLR_002/anomalies")
        data = resp.json()
        types = [a["type"] for a in data["anomalies"]]
        assert "BILLING_QUEUE_SPIKE" not in types
