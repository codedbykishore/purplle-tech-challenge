"""
PROMPT: Generate tests for GET /stores/{id}/metrics covering required fields, staff exclusion, dwell averages, and zero-purchase scenarios.

CHANGES MADE: Manually added edge cases for all-staff scenarios, zero purchases conversion rate, and re-entry not double-counted.
"""

import pytest


class TestMetrics:
    def test_metrics_returns_200(self, client):
        resp = client.get("/stores/STORE_BLR_002/metrics")
        assert resp.status_code == 200

    def test_metrics_has_required_fields(self, client):
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        required = ["store_id", "unique_visitors", "conversion_rate",
                     "avg_dwell_per_zone", "current_queue_depth",
                     "abandonment_rate", "total_entries", "total_exits",
                     "staff_excluded_count"]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_metrics_empty_store_returns_zeros(self, client):
        """Test metrics for store with no events."""
        resp = client.get("/stores/STORE_EMPTY/metrics")
        data = resp.json()
        assert data["unique_visitors"] == 0
        assert data["total_entries"] == 0

    def test_metrics_excludes_staff(self, client):
        """Test that staff events don't inflate visitor count."""
        # Ingest staff and customer events
        staff_event = {
            "event_id": "550e8400-e29b-41d4-a716-000000000001",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_MAIN_01",
            "visitor_id": "STAFF_001", "event_type": "ENTRY",
            "timestamp": "2026-04-10T11:00:00Z", "dwell_ms": 0,
            "is_staff": True, "confidence": 0.9,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
        }
        cust_event = {
            "event_id": "550e8400-e29b-41d4-a716-000000000002",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_MAIN_01",
            "visitor_id": "VIS_cust001", "event_type": "ENTRY",
            "timestamp": "2026-04-10T11:01:00Z", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.9,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
        }
        client.post("/events/ingest", json={"events": [staff_event, cust_event]})
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        assert data["unique_visitors"] == 1  # Only customer, not staff
        assert data["staff_excluded_count"] == 1

    def test_metrics_avg_dwell_per_zone(self, client):
        """Test avg_dwell_per_zone computation with ZONE_DWELL events."""
        events = [
            {
                "event_id": f"550e8400-e29b-41d4-a716-{i:012d}",
                "store_id": "STORE_BLR_002", "camera_id": "CAM_MAIN_01",
                "visitor_id": f"VIS_dwell{i}", "event_type": "ZONE_DWELL",
                "timestamp": f"2026-04-10T11:0{i}:00Z",
                "zone_id": "BROWSING", "dwell_ms": 5000,
                "is_staff": False, "confidence": 0.8,
                "metadata": {"sku_zone": "A1"},
            }
            for i in range(3)
        ]
        client.post("/events/ingest", json={"events": events})
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        assert "BROWSING" in data["avg_dwell_per_zone"]
        assert data["avg_dwell_per_zone"]["BROWSING"] == 5000

    def test_metrics_queue_depth(self, client):
        """Test current_queue_depth from BILLING_QUEUE_JOIN metadata."""
        event = {
            "event_id": "550e8400-e29b-41d4-a716-999999999999",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_BILLING_01",
            "visitor_id": "VIS_queue", "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-04-10T11:00:00Z",
            "zone_id": "BILLING", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.9,
            "metadata": {"queue_depth": 3},
        }
        client.post("/events/ingest", json={"events": [event]})
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        assert data["current_queue_depth"] == 3

    def test_metrics_abandonment_rate(self, client):
        """Test abandonment_rate calculation."""
        join_event = {
            "event_id": "550e8400-e29b-41d4-a716-aaaa00000001",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_BILLING_01",
            "visitor_id": "VIS_abandon", "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-04-10T11:00:00Z",
            "zone_id": "BILLING", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.9,
            "metadata": {"queue_depth": 2},
        }
        abandon_event = {
            "event_id": "550e8400-e29b-41d4-a716-aaaa00000002",
            "store_id": "STORE_BLR_002", "camera_id": "CAM_BILLING_01",
            "visitor_id": "VIS_abandon", "event_type": "BILLING_QUEUE_ABANDON",
            "timestamp": "2026-04-10T11:05:00Z",
            "zone_id": "BILLING", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.9,
            "metadata": {},
        }
        client.post("/events/ingest", json={"events": [join_event, abandon_event]})
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        # 1 abandon / (1 join + 1 abandon) = 0.5
        assert data["abandonment_rate"] == 0.5

    def test_all_staff_zero_customer_metrics(self, client):
        """Test that all-staff clip results in zero customer metrics."""
        # Ingest 3 staff events, 0 customer events
        events = []
        for i in range(3):
            events.append({
                "event_id": f"550e8400-e29b-41d4-a716-staff{i:09d}",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_MAIN_01",
                "visitor_id": f"STAFF_{i:03d}",
                "event_type": "ENTRY",
                "timestamp": f"2026-04-10T11:0{i}:00Z",
                "dwell_ms": 0,
                "is_staff": True,
                "confidence": 0.9,
                "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
            })
        client.post("/events/ingest", json={"events": events})
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        assert data["unique_visitors"] == 0
        assert data["staff_excluded_count"] == 3

    def test_zero_purchases_conversion_rate_zero(self, client):
        """Test that zero purchases results in conversion_rate=0."""
        # Ingest entries but no billing/purchase events
        events = []
        for i in range(3):
            events.append({
                "event_id": f"550e8400-e29b-41d4-a716-nopurch{i:09d}",
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": f"VIS_no{i:03d}",
                "event_type": "ENTRY",
                "timestamp": f"2026-04-10T11:0{i}:00Z",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
            })
        client.post("/events/ingest", json={"events": events})
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        assert data["conversion_rate"] == 0.0

    def test_reentry_not_double_counted(self, client):
        """Test that re-entry doesn't inflate unique visitor count."""
        events = [
            # First visit
            {"event_id": "550e8400-e29b-41d4-a716-re000000001",
             "store_id": "STORE_BLR_002", "camera_id": "CAM_ENTRY_01",
             "visitor_id": "VIS_re001", "event_type": "ENTRY",
             "timestamp": "2026-04-10T11:00:00Z", "dwell_ms": 0,
             "is_staff": False, "confidence": 0.9,
             "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}},
            {"event_id": "550e8400-e29b-41d4-a716-re000000002",
             "store_id": "STORE_BLR_002", "camera_id": "CAM_ENTRY_01",
             "visitor_id": "VIS_re001", "event_type": "EXIT",
             "timestamp": "2026-04-10T11:05:00Z", "dwell_ms": 0,
             "is_staff": False, "confidence": 0.9,
             "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 2}},
            # Re-entry
            {"event_id": "550e8400-e29b-41d4-a716-re000000003",
             "store_id": "STORE_BLR_002", "camera_id": "CAM_ENTRY_01",
             "visitor_id": "VIS_re001", "event_type": "REENTRY",
             "timestamp": "2026-04-10T11:08:00Z", "dwell_ms": 0,
             "is_staff": False, "confidence": 0.7,
             "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 3}},
        ]
        client.post("/events/ingest", json={"events": events})
        resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        # Same visitor_id should be counted once
        assert data["unique_visitors"] == 1
