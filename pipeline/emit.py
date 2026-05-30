"""
Event schema definition and emission helpers for the detection pipeline.

The detection pipeline (detect.py) will use these helpers to emit structured
events from YOLOv8 + ByteTrack tracking output.
"""

import uuid
from datetime import datetime
from typing import Any

# Valid event types from the problem statement
EVENT_TYPES = frozenset({
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
})


def emit_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.0,
    queue_depth: int | None = None,
    sku_zone: str | None = None,
    session_seq: int = 1,
) -> dict[str, Any]:
    """Create a structured event dict matching the required schema."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}. Must be one of {sorted(EVENT_TYPES)}")

    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": round(confidence, 2),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": sku_zone,
            "session_seq": session_seq,
        },
    }


def emit_entry(store_id, camera_id, visitor_id, timestamp, is_staff=False, confidence=0.9):
    """Shorthand for ENTRY event."""
    return emit_event(store_id, camera_id, visitor_id, "ENTRY", timestamp,
                      is_staff=is_staff, confidence=confidence)


def emit_exit(store_id, camera_id, visitor_id, timestamp, is_staff=False, confidence=0.9):
    """Shorthand for EXIT event."""
    return emit_event(store_id, camera_id, visitor_id, "EXIT", timestamp,
                      is_staff=is_staff, confidence=confidence)


def emit_zone_enter(store_id, camera_id, visitor_id, timestamp, zone_id,
                    is_staff=False, confidence=0.8):
    """Shorthand for ZONE_ENTER event."""
    return emit_event(store_id, camera_id, visitor_id, "ZONE_ENTER", timestamp,
                      zone_id=zone_id, is_staff=is_staff, confidence=confidence)


def emit_zone_exit(store_id, camera_id, visitor_id, timestamp, zone_id,
                   is_staff=False, confidence=0.8):
    """Shorthand for ZONE_EXIT event."""
    return emit_event(store_id, camera_id, visitor_id, "ZONE_EXIT", timestamp,
                      zone_id=zone_id, is_staff=is_staff, confidence=confidence)


def emit_zone_dwell(store_id, camera_id, visitor_id, timestamp, zone_id,
                    dwell_ms, is_staff=False, confidence=0.8, sku_zone=None):
    """Shorthand for ZONE_DWELL event."""
    return emit_event(store_id, camera_id, visitor_id, "ZONE_DWELL", timestamp,
                      zone_id=zone_id, dwell_ms=dwell_ms, is_staff=is_staff,
                      confidence=confidence, sku_zone=sku_zone)


def emit_billing_queue_join(store_id, camera_id, visitor_id, timestamp,
                            queue_depth, confidence=0.8):
    """Shorthand for BILLING_QUEUE_JOIN event."""
    return emit_event(store_id, camera_id, visitor_id, "BILLING_QUEUE_JOIN", timestamp,
                      zone_id="BILLING", queue_depth=queue_depth, confidence=confidence)


def emit_billing_queue_abandon(store_id, camera_id, visitor_id, timestamp,
                               confidence=0.8):
    """Shorthand for BILLING_QUEUE_ABANDON event."""
    return emit_event(store_id, camera_id, visitor_id, "BILLING_QUEUE_ABANDON", timestamp,
                      zone_id="BILLING", confidence=confidence)


def emit_reentry(store_id, camera_id, visitor_id, timestamp, confidence=0.7):
    """Shorthand for REENTRY event."""
    return emit_event(store_id, camera_id, visitor_id, "REENTRY", timestamp,
                      confidence=confidence)


def events_to_jsonl(events: list[dict], filepath: str):
    """Write a list of events to a JSONL file."""
    import json
    with open(filepath, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def events_from_jsonl(filepath: str) -> list[dict]:
    """Read events from a JSONL file. Skips malformed lines with a warning."""
    import json
    import warnings
    events = []
    with open(filepath) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    warnings.warn(f"Skipping malformed JSON at line {line_num}: {e}")
    return events
