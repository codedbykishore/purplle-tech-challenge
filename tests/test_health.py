"""
PROMPT: Generate tests for GET /health endpoint covering status codes, response structure, and stale feed detection.

CHANGES MADE: Manually added edge cases for database unavailable (503) and stale feed warnings.
"""

import pytest


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_status_healthy(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")

    def test_health_has_required_fields(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data
        assert "uptime_seconds" in data
        assert "stores" in data
        assert "warnings" in data
        assert isinstance(data["stores"], dict)
        assert isinstance(data["warnings"], list)

    def test_health_includes_ingested_store(self, client, sample_event):
        """Test health includes store data after ingesting events."""
        client.post("/events/ingest", json={"events": [sample_event]})
        resp = client.get("/health")
        data = resp.json()
        assert "STORE_BLR_002" in data["stores"]
        store_health = data["stores"]["STORE_BLR_002"]
        assert store_health["last_event_at"] is not None

    def test_stale_feed_warning(self, client, temp_db):
        """Test that stale events (>10 min old) trigger a warning."""
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute(
            """INSERT INTO events (event_id, store_id, camera_id, visitor_id,
               event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("old-event-001", "STORE_STALE", "CAM_MAIN_01", "VIS_old01",
             "ENTRY", "2026-04-10T01:00:00Z", None, 0, False, 0.9, "{}"),
        )
        conn.commit()
        conn.close()

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert any("STALE_FEED" in w for w in data["warnings"])


class TestDatabaseUnavailable:
    def test_db_unavailable_returns_503(self, temp_db, monkeypatch):
        """Test that DB failure returns 503 with structured error."""
        from fastapi.testclient import TestClient
        from app.main import app

        def broken_db():
            raise Exception("Database connection failed")

        monkeypatch.setattr("app.main.get_database", broken_db)

        test_client = TestClient(app, raise_server_exceptions=False)
        resp = test_client.get("/health")
        assert resp.status_code == 503
        data = resp.json()
        assert "detail" in data
        assert "error" in data["detail"]
