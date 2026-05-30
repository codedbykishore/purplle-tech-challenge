"""
Event schema validator for the detection pipeline.

Validates events against 15+ rules before they reach the API.
Run as: python pipeline/validate.py data/events.jsonl
"""

import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Valid event types
VALID_EVENT_TYPES = {
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
}

# Event types that must NOT have a zone_id
ENTRY_EXIT_TYPES = {"ENTRY", "EXIT"}

# Event types that MUST have a zone_id
ZONE_REQUIRED_TYPES = {
    "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON",
}

# Event types where dwell_ms should be 0 (instantaneous)
INSTANTANEOUS_TYPES = {"ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "REENTRY"}


class ValidationError:
    def __init__(self, event_id: str, rule: str, message: str, severity: str = "ERROR"):
        self.event_id = event_id
        self.rule = rule
        self.message = message
        self.severity = severity

    def __str__(self):
        return f"[{self.severity}] {self.event_id} | {self.rule}: {self.message}"


def validate_event(event: dict, known_stores: set[str] | None = None,
                   known_zones: set[str] | None = None) -> list[ValidationError]:
    """Validate a single event against all rules. Returns list of errors."""
    errors = []
    event_id = event.get("event_id", "UNKNOWN")

    # Rule 1: event_id is valid UUID v4
    event_id_raw = event.get("event_id")
    if not event_id_raw:
        errors.append(ValidationError("UNKNOWN", "RULE_01", "event_id is missing or empty"))
        return errors  # Can't continue without event_id
    try:
        parsed_uuid = uuid.UUID(str(event_id_raw))
        if parsed_uuid.version != 4:
            errors.append(ValidationError(event_id, "RULE_01",
                f"event_id must be UUID v4, got v{parsed_uuid.version}"))
    except (ValueError, TypeError):
        errors.append(ValidationError(event_id, "RULE_01",
            f"event_id '{event_id_raw}' is not a valid UUID"))

    # Rule 2: store_id is present
    if not event.get("store_id"):
        errors.append(ValidationError(event_id, "RULE_02", "store_id is missing"))

    # Rule 3: store_id matches known stores (if provided)
    if known_stores and event.get("store_id") not in known_stores:
        errors.append(ValidationError(event_id, "RULE_03",
            f"store_id '{event.get('store_id')}' not in known stores: {sorted(known_stores)}"))

    # Rule 4: camera_id matches CAM_*_NN pattern
    camera_id = event.get("camera_id", "")
    if not re.match(r"^CAM_[A-Z_]+_\d{2}$", camera_id):
        errors.append(ValidationError(event_id, "RULE_04",
            f"camera_id '{camera_id}' does not match CAM_*_NN pattern"))

    # Rule 5: visitor_id matches VIS_* or STAFF_* pattern
    visitor_id = event.get("visitor_id", "")
    if not (visitor_id.startswith("VIS_") or visitor_id.startswith("STAFF_")):
        errors.append(ValidationError(event_id, "RULE_05",
            f"visitor_id '{visitor_id}' does not match VIS_* or STAFF_* pattern"))

    # Rule 6: event_type is one of the 8 allowed values
    event_type = event.get("event_type", "")
    if event_type not in VALID_EVENT_TYPES:
        errors.append(ValidationError(event_id, "RULE_06",
            f"event_type '{event_type}' not in {sorted(VALID_EVENT_TYPES)}"))

    # Rule 7: timestamp is valid ISO-8601 UTC
    timestamp = event.get("timestamp", "")
    try:
        normalized = timestamp.replace("Z", "+00:00")
        parsed_ts = datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        errors.append(ValidationError(event_id, "RULE_07",
            f"timestamp '{timestamp}' is not valid ISO-8601 UTC"))
        parsed_ts = None

    # Rule 8: zone_id is null for ENTRY/EXIT, valid zone for others
    zone_id = event.get("zone_id")
    if event_type in ENTRY_EXIT_TYPES:
        if zone_id is not None:
            errors.append(ValidationError(event_id, "RULE_08",
                f"zone_id must be null for {event_type}, got '{zone_id}'"))
    elif event_type in ZONE_REQUIRED_TYPES:
        if zone_id is None:
            errors.append(ValidationError(event_id, "RULE_08",
                f"zone_id must not be null for {event_type}"))
        elif known_zones and zone_id not in known_zones:
            errors.append(ValidationError(event_id, "RULE_08",
                f"zone_id '{zone_id}' not in known zones: {sorted(known_zones)}"))

    # Rule 9: dwell_ms is integer >= 0 (not boolean)
    dwell_ms = event.get("dwell_ms", 0)
    if isinstance(dwell_ms, bool) or not isinstance(dwell_ms, int) or dwell_ms < 0:
        errors.append(ValidationError(event_id, "RULE_09",
            f"dwell_ms must be non-negative integer, got {dwell_ms}"))

    # Rule 10: dwell_ms is 0 for instantaneous events
    if event_type in INSTANTANEOUS_TYPES and dwell_ms != 0:
        errors.append(ValidationError(event_id, "RULE_10",
            f"dwell_ms must be 0 for {event_type}, got {dwell_ms}"))

    # Rule 11: is_staff is boolean
    is_staff = event.get("is_staff")
    if not isinstance(is_staff, bool):
        errors.append(ValidationError(event_id, "RULE_11",
            f"is_staff must be boolean, got {type(is_staff).__name__}: {is_staff}"))

    # Rule 12: confidence is float between 0.0 and 1.0 (not boolean)
    confidence = event.get("confidence", 0.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        errors.append(ValidationError(event_id, "RULE_12",
            f"confidence must be 0.0-1.0, got {confidence}"))

    # Rule 13: metadata is present and is a dict
    metadata = event.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append(ValidationError(event_id, "RULE_13",
            f"metadata must be a dict or null, got {type(metadata).__name__}"))

    # Rule 14: metadata structure is correct for event type
    if isinstance(metadata, dict):
        if event_type == "BILLING_QUEUE_JOIN":
            if "queue_depth" not in metadata:
                errors.append(ValidationError(event_id, "RULE_14",
                    "BILLING_QUEUE_JOIN must have queue_depth in metadata"))
            elif metadata["queue_depth"] is not None and not isinstance(metadata["queue_depth"], int):
                errors.append(ValidationError(event_id, "RULE_14",
                    f"metadata.queue_depth must be int or null, got {type(metadata['queue_depth']).__name__}"))
        if event_type == "ZONE_DWELL":
            if "sku_zone" not in metadata:
                errors.append(ValidationError(event_id, "RULE_14",
                    "ZONE_DWELL should have sku_zone in metadata"))
        if "session_seq" in metadata and not isinstance(metadata["session_seq"], (int, type(None))):
            errors.append(ValidationError(event_id, "RULE_14",
                f"metadata.session_seq must be int or null, got {type(metadata['session_seq']).__name__}"))

    # Rule 15: confidence < 0.3 flagged as low-quality (warning, not error)
    if isinstance(confidence, (int, float)) and 0.0 <= confidence < 0.3:
        errors.append(ValidationError(event_id, "RULE_15",
            f"Low confidence detection: {confidence}", severity="WARN"))

    return errors


def validate_file(filepath: str, known_stores: set[str] | None = None,
                  known_zones: set[str] | None = None) -> tuple[int, int, list[ValidationError]]:
    """Validate all events in a JSONL file. Returns (total, valid_count, errors)."""
    total = 0
    valid = 0
    all_errors = []

    with open(filepath) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                all_errors.append(ValidationError(
                    f"LINE_{line_num}", "JSON_PARSE", f"Invalid JSON: {e}"))
                continue

            errors = validate_event(event, known_stores, known_zones)
            if not errors:
                valid += 1
            all_errors.extend(errors)

    return total, valid, all_errors


def load_store_layout(layout_path: str) -> tuple[set[str], set[str]]:
    """Load store IDs and zone IDs from store_layout.json."""
    with open(layout_path) as f:
        layout = json.load(f)

    stores = set()
    zones = set()
    for store in layout.get("stores", []):
        stores.add(store["store_id"])
        for zone in store.get("zones", []):
            zones.add(zone["zone_id"])
    return stores, zones


def main():
    """CLI entry point: python pipeline/validate.py <events.jsonl> [--layout store_layout.json]"""
    if len(sys.argv) < 2:
        print("Usage: python pipeline/validate.py <events.jsonl> [--layout store_layout.json]")
        sys.exit(1)

    events_path = sys.argv[1]
    layout_path = None

    if "--layout" in sys.argv:
        idx = sys.argv.index("--layout")
        if idx + 1 < len(sys.argv):
            layout_path = sys.argv[idx + 1]

    known_stores = None
    known_zones = None
    if layout_path and Path(layout_path).exists():
        known_stores, known_zones = load_store_layout(layout_path)

    total, valid, errors = validate_file(events_path, known_stores, known_zones)

    # Summary
    print(f"\nValidation Report: {events_path}")
    print(f"{'='*60}")
    print(f"Total events:   {total}")
    print(f"Valid events:   {valid}")
    print(f"Invalid events: {total - valid}")

    # Group errors by severity
    real_errors = [e for e in errors if e.severity == "ERROR"]
    warnings = [e for e in errors if e.severity == "WARN"]

    if real_errors:
        print(f"\nErrors ({len(real_errors)}):")
        for e in real_errors[:20]:  # Show first 20
            print(f"  {e}")
        if len(real_errors) > 20:
            print(f"  ... and {len(real_errors) - 20} more errors")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings[:10]:
            print(f"  {w}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more warnings")

    print(f"\n{'='*60}")
    if real_errors:
        print(f"FAILED: {len(real_errors)} errors found")
        sys.exit(1)
    else:
        print("PASSED: All events valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
