"""
Event ingestion logic — extracted for clarity and testability.

Provides a standalone function to ingest a batch of events into the
database, with idempotency checks and error reporting.
"""

import json

from app.database import get_database


def ingest_event_batch(events: list[dict]) -> tuple[int, int, list[dict]]:
    """Ingest a batch of events into the database.

    Args:
        events: List of event dicts. Each dict must include at minimum:
            event_id, store_id, camera_id, visitor_id, event_type, timestamp.

    Returns:
        Tuple of (accepted, rejected, errors) where errors is a list of
        dicts with 'event_id' and 'error' keys.
    """
    accepted = 0
    rejected = 0
    errors = []

    conn = get_database()
    try:
        for event in events:
            try:
                # Idempotency check
                existing = conn.execute(
                    "SELECT 1 FROM events WHERE event_id = ?",
                    (event["event_id"],),
                ).fetchone()

                if existing:
                    # Already ingested — skip (idempotent, don't count as accepted)
                    continue

                conn.execute(
                    """INSERT INTO events
                       (event_id, store_id, camera_id, visitor_id, event_type,
                        timestamp, zone_id, dwell_ms, is_staff, confidence, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event["event_id"],
                        event["store_id"],
                        event["camera_id"],
                        event["visitor_id"],
                        event["event_type"],
                        event["timestamp"],
                        event.get("zone_id"),
                        event.get("dwell_ms", 0),
                        event.get("is_staff", False),
                        event.get("confidence", 0.0),
                        json.dumps(event.get("metadata", {})),
                    ),
                )
                accepted += 1
            except Exception as e:
                rejected += 1
                errors.append(
                    {"event_id": event.get("event_id", "?"), "error": str(e)}
                )

        conn.commit()
    finally:
        conn.close()

    return accepted, rejected, errors
