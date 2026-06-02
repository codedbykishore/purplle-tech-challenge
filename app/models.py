"""
Pydantic v2 models for the Store Intelligence API.
"""

from pydantic import BaseModel, Field, field_validator


VALID_EVENT_TYPES = frozenset({
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
})

SEVERITY_LEVELS = frozenset({"INFO", "WARN", "CRITICAL"})

ANOMALY_TYPES = frozenset({"BILLING_QUEUE_SPIKE", "CONVERSION_DROP", "DEAD_ZONE"})

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})


# ──────────────────────────────────────────────
# Event ingest models
# ──────────────────────────────────────────────


class EventMetadata(BaseModel):
    queue_depth: int | None = None
    sku_zone: str | None = None
    session_seq: int | None = None


class EventIngest(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str  # ISO-8601 UTC
    zone_id: str | None = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = 0.0
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type '{v}'. Must be one of {sorted(VALID_EVENT_TYPES)}"
            )
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("dwell_ms")
    @classmethod
    def validate_dwell_ms(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"dwell_ms must be >= 0, got {v}")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        from datetime import datetime
        try:
            # Handle both Z suffix and +00:00
            normalized = v.replace("Z", "+00:00")
            datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            raise ValueError(f"timestamp must be valid ISO-8601 UTC, got '{v}'")
        return v


class EventBatch(BaseModel):
    events: list[EventIngest]


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    errors: list[dict] = []


# ──────────────────────────────────────────────
# Metrics models
# ──────────────────────────────────────────────


class MetricsResponse(BaseModel):
    store_id: str
    date: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_per_zone: dict[str, int]
    current_queue_depth: int
    queue_depth: int = 0  # Alias for current_queue_depth
    abandonment_rate: float
    total_entries: int
    total_exits: int
    staff_excluded_count: int


# ──────────────────────────────────────────────
# Funnel models
# ──────────────────────────────────────────────


class FunnelStage(BaseModel):
    name: str
    count: int
    dropoff_pct: float

    @field_validator("dropoff_pct")
    @classmethod
    def validate_dropoff_pct(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError(f"dropoff_pct must be between 0.0 and 100.0, got {v}")
        return v


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage]
    overall_conversion: float


# ──────────────────────────────────────────────
# Heatmap models
# ──────────────────────────────────────────────


class HeatmapZone(BaseModel):
    zone_id: str
    visit_count: int
    avg_dwell_ms: int
    score: int  # 0-100

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError(f"score must be between 0 and 100, got {v}")
        return v


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[HeatmapZone]
    data_confidence: str  # "high", "medium", "low"

    @field_validator("data_confidence")
    @classmethod
    def validate_confidence_level(cls, v: str) -> str:
        if v not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"data_confidence must be one of {sorted(CONFIDENCE_LEVELS)}, got '{v}'"
            )
        return v


# ──────────────────────────────────────────────
# Anomaly models
# ──────────────────────────────────────────────


class Anomaly(BaseModel):
    type: str  # BILLING_QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE
    severity: str  # INFO, WARN, CRITICAL
    description: str
    detected_at: str
    suggested_action: str

    @field_validator("type")
    @classmethod
    def validate_anomaly_type(cls, v: str) -> str:
        if v not in ANOMALY_TYPES:
            raise ValueError(
                f"Invalid anomaly type '{v}'. Must be one of {sorted(ANOMALY_TYPES)}"
            )
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in SEVERITY_LEVELS:
            raise ValueError(
                f"Invalid severity '{v}'. Must be one of {sorted(SEVERITY_LEVELS)}"
            )
        return v


class AnomalyResponse(BaseModel):
    store_id: str
    anomalies: list[Anomaly]


# ──────────────────────────────────────────────
# Health models
# ──────────────────────────────────────────────


class StoreHealth(BaseModel):
    last_event_at: str | None = None
    status: str = "active"
    event_count_today: int = 0


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    stores: dict[str, StoreHealth]
    warnings: list[str] = []
