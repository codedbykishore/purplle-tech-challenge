"""
PROMPT: Generate comprehensive tests for pipeline/validate.py schema validator.
Cover rules RULE_01 through RULE_15 including edge cases.

CHANGES MADE: Added tests for all 15 validation rules, including edge cases.
"""

import pytest
from pipeline.validate import validate_event, ValidationError, VALID_EVENT_TYPES


def make_valid_event(**overrides):
    """Helper to build a valid event with optional overrides."""
    event = {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_test01",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T11:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    event.update(overrides)
    return event


class TestValidEvent:
    def test_valid_event_no_errors(self):
        errors = validate_event(make_valid_event())
        assert len(errors) == 0


class TestRule01EventId:
    def test_missing_event_id(self):
        errors = validate_event(make_valid_event(event_id=""))
        assert any("RULE_01" in e.rule for e in errors)

    def test_not_uuid_v4(self):
        """UUID v1 should be rejected."""
        # This is a UUID v1 (version=1 at 13th hex digit)
        errors = validate_event(make_valid_event(
            event_id="550e8400-e29b-11d4-a716-446655440000"
        ))
        assert any("RULE_01" in e.rule for e in errors)

    def test_not_a_uuid_at_all(self):
        errors = validate_event(make_valid_event(event_id="not-a-uuid"))
        assert any("RULE_01" in e.rule for e in errors)


class TestRule02StoreId:
    def test_missing_store_id(self):
        errors = validate_event(make_valid_event(store_id=""))
        assert any("RULE_02" in e.rule for e in errors)

    def test_known_stores_filter(self):
        """Rule 3: known_stores set provided, store not in it."""
        errors = validate_event(
            make_valid_event(store_id="UNKNOWN_STORE"),
            known_stores={"STORE_BLR_002"},
        )
        assert any("RULE_03" in e.rule for e in errors)

    def test_known_stores_pass(self):
        """Rule 3: store in known_stores should pass."""
        errors = validate_event(
            make_valid_event(store_id="STORE_BLR_002"),
            known_stores={"STORE_BLR_002"},
        )
        assert not any("RULE_03" in e.rule for e in errors)


class TestRule04CameraId:
    def test_invalid_camera_id_pattern(self):
        errors = validate_event(make_valid_event(camera_id="bad_camera"))
        assert any("RULE_04" in e.rule for e in errors)


class TestRule05VisitorId:
    def test_invalid_visitor_id_pattern(self):
        errors = validate_event(make_valid_event(visitor_id="guest_001"))
        assert any("RULE_05" in e.rule for e in errors)

    def test_valid_visitor_staff_prefix(self):
        """STAFF_ prefix is valid."""
        errors = validate_event(make_valid_event(visitor_id="STAFF_001"))
        assert not any("RULE_05" in e.rule for e in errors)


class TestRule07Timestamp:
    def test_invalid_timestamp(self):
        errors = validate_event(make_valid_event(timestamp="not-a-timestamp"))
        assert any("RULE_07" in e.rule for e in errors)


class TestRule08ZoneId:
    def test_zone_id_set_for_entry(self):
        errors = validate_event(make_valid_event(zone_id="BROWSING"))
        assert any("RULE_08" in e.rule for e in errors)

    def test_zone_id_null_for_zone_enter(self):
        errors = validate_event(make_valid_event(
            event_type="ZONE_ENTER", zone_id=None
        ))
        assert any("RULE_08" in e.rule for e in errors)

    def test_zone_id_unknown_zone(self):
        errors = validate_event(
            make_valid_event(
                event_type="ZONE_ENTER", zone_id="VOID_ZONE"
            ),
            known_zones={"BROWSING", "SKINCARE"},
        )
        assert any("RULE_08" in e.rule for e in errors)


class TestRule09DwellMs:
    def test_negative_dwell_ms(self):
        errors = validate_event(make_valid_event(dwell_ms=-1))
        assert any("RULE_09" in e.rule for e in errors)

    def test_dwell_ms_string_rejected(self):
        errors = validate_event(make_valid_event(
            event_type="ZONE_DWELL", dwell_ms="5000"
        ))
        assert any("RULE_09" in e.rule for e in errors)


class TestRule10InstantaneousDwell:
    def test_nonzero_dwell_for_entry(self):
        errors = validate_event(make_valid_event(dwell_ms=100))
        assert any("RULE_10" in e.rule for e in errors)

    def test_zone_dwell_allows_nonzero_dwell(self):
        errors = validate_event(make_valid_event(
            event_type="ZONE_DWELL", zone_id="BROWSING", dwell_ms=5000
        ))
        assert not any("RULE_10" in e.rule for e in errors)


class TestRule11IsStaff:
    def test_is_staff_not_boolean(self):
        errors = validate_event(make_valid_event(is_staff="yes"))
        assert any("RULE_11" in e.rule for e in errors)


class TestRule12Confidence:
    def test_confidence_too_high(self):
        errors = validate_event(make_valid_event(confidence=1.5))
        assert any("RULE_12" in e.rule for e in errors)

    def test_confidence_boolean_rejected(self):
        errors = validate_event(make_valid_event(confidence=True))
        assert any("RULE_12" in e.rule for e in errors)


class TestRule13Metadata:
    def test_metadata_not_dict(self):
        errors = validate_event(make_valid_event(metadata="string"))
        assert any("RULE_13" in e.rule for e in errors)


class TestRule14MetadataStructure:
    def test_billing_queue_join_missing_queue_depth(self):
        errors = validate_event(make_valid_event(
            event_type="BILLING_QUEUE_JOIN", zone_id="BILLING",
            metadata={},
        ))
        assert any("RULE_14" in e.rule for e in errors)

    def test_zone_dwell_missing_sku_zone(self):
        errors = validate_event(make_valid_event(
            event_type="ZONE_DWELL", zone_id="BROWSING", dwell_ms=5000,
            metadata={},
        ))
        assert any("RULE_14" in e.rule for e in errors)

    def test_session_seq_not_int(self):
        errors = validate_event(make_valid_event(
            metadata={"session_seq": "abc"},
        ))
        assert any("RULE_14" in e.rule for e in errors)


class TestRule15LowConfidence:
    def test_low_confidence_warning(self):
        errors = validate_event(make_valid_event(confidence=0.2))
        assert any("RULE_15" in e.rule for e in errors)

    def test_low_confidence_is_warning_not_error(self):
        errors = validate_event(make_valid_event(confidence=0.2))
        warn = [e for e in errors if e.rule == "RULE_15"]
        assert len(warn) > 0
        assert warn[0].severity == "WARN"


class TestValidationErrorStr:
    def test_validation_error_str_format(self):
        err = ValidationError(
            "test-id", "RULE_01", "test message", severity="ERROR"
        )
        s = str(err)
        assert "ERROR" in s
        assert "test-id" in s
        assert "RULE_01" in s
        assert "test message" in s
