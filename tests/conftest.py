"""
PROMPT: Shared pytest fixtures for the Store Intelligence test suite including temp_db, client, sample_event, and sample_events_batch.

CHANGES MADE: None (AI-generated fixtures for all tests).
"""

import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Set test database path before importing app
os.environ["DATABASE_PATH"] = ""  # Will be overridden per test

from app.main import app
from app.database import init_database, get_database, DATABASE_PATH


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for each test."""
    db_path = str(tmp_path / "test.db")
    os.environ["DATABASE_PATH"] = db_path
    
    # Patch the module-level DATABASE_PATH
    import app.database
    original = app.database.DATABASE_PATH
    app.database.DATABASE_PATH = db_path
    
    # Re-init with new path
    init_database()
    
    yield db_path
    
    # Restore
    app.database.DATABASE_PATH = original
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def client(temp_db):
    """Create a test client with a fresh database."""
    return TestClient(app)


@pytest.fixture
def sample_event():
    """Return a valid sample event."""
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_test001",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T11:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }


@pytest.fixture
def sample_events_batch():
    """Return a batch of 5 valid events."""
    events = []
    for i in range(5):
        events.append({
            "event_id": f"550e8400-e29b-41d4-a716-44665544{i:04d}",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_MAIN_01",
            "visitor_id": f"VIS_batch{i:03d}",
            "event_type": "ZONE_ENTER",
            "timestamp": f"2026-04-10T11:{10+i}:00Z",
            "zone_id": "BROWSING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.8,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": i+1},
        })
    return events
