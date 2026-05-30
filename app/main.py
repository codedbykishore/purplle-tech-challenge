"""
Store Intelligence API — FastAPI application entry point.

Endpoints:
  POST /events/ingest    — Ingest batch of events (up to 500, idempotent)
  GET  /health           — Service health with per-store status
  GET  /stores/{id}/metrics   — Real-time store metrics
  GET  /stores/{id}/funnel    — Conversion funnel
  GET  /stores/{id}/heatmap   — Zone heatmap data
  GET  /stores/{id}/anomalies — Anomaly detection
  GET  /dashboard            — Web dashboard (HTML)
"""

import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse

from app.database import get_database, init_database, seed_pos_data
from app.models import (
    EventBatch,
    IngestResponse,
    HealthResponse,
    StoreHealth,
)
from app.session import SessionManager

# ──────────────────────────────────────────────
# Structured Logging
# ──────────────────────────────────────────────

logger = structlog.get_logger()

# ──────────────────────────────────────────────
# App State
# ──────────────────────────────────────────────

_start_time = time.time()
_session_manager = SessionManager()


# ──────────────────────────────────────────────
# Lifespan (startup/shutdown)
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_database()
    seed_pos_data()
    logger.info("server_started", uptime=0)
    yield
    logger.info("server_stopped")


app = FastAPI(
    title="Store Intelligence API",
    description="Real-time retail analytics from CCTV footage",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Middleware: Request Logging
# ──────────────────────────────────────────────

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    start = time.time()

    response = await call_next(request)

    latency_ms = (time.time() - start) * 1000
    logger.info(
        "request_completed",
        trace_id=trace_id,
        store_id=request.path_params.get("store_id", "N/A"),
        endpoint=f"{request.method} {request.url.path}",
        latency_ms=round(latency_ms, 2),
        status_code=response.status_code,
    )
    return response


# ──────────────────────────────────────────────
# Global Exception Handler
# ──────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=503,
        content={
            "error": "service_unavailable",
            "message": "An internal error occurred",
            "trace_id": str(uuid.uuid4()),
        },
    )


# ──────────────────────────────────────────────
# POST /events/ingest
# ──────────────────────────────────────────────

@app.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(batch: EventBatch):
    """Accept a batch of events (up to 500). Idempotent by event_id."""
    if len(batch.events) > 500:
        raise HTTPException(status_code=400, detail="Batch size exceeds 500")

    accepted = 0
    rejected = 0
    errors = []

    conn = get_database()
    try:
        for event in batch.events:
            try:
                # Check idempotency
                existing = conn.execute(
                    "SELECT 1 FROM events WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()

                if existing:
                    # Already ingested — skip (idempotent, don't count as accepted)
                    continue

                # Insert event
                conn.execute(
                    """INSERT INTO events
                       (event_id, store_id, camera_id, visitor_id, event_type,
                        timestamp, zone_id, dwell_ms, is_staff, confidence, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.event_id,
                        event.store_id,
                        event.camera_id,
                        event.visitor_id,
                        event.event_type,
                        event.timestamp,
                        event.zone_id,
                        event.dwell_ms,
                        event.is_staff,
                        event.confidence,
                        json.dumps(event.metadata.model_dump()),
                    ),
                )
                accepted += 1

                # Update session manager
                if event.event_type == "ENTRY":
                    _session_manager.create_session(
                        event.visitor_id, event.store_id, event.model_dump()
                    )
                elif event.event_type == "EXIT":
                    _session_manager.close_session(
                        event.visitor_id, event.model_dump()
                    )
                elif event.event_type == "ZONE_ENTER" and event.zone_id == "BILLING":
                    _session_manager.update_billing_entry(
                        event.visitor_id,
                        datetime.fromisoformat(
                            event.timestamp.replace("Z", "+00:00")
                        ),
                    )

            except Exception as e:
                rejected += 1
                errors.append({"event_id": event.event_id, "error": str(e)})

        conn.commit()
    finally:
        conn.close()

    logger.info("events_ingested", accepted=accepted, rejected=rejected)
    return IngestResponse(accepted=accepted, rejected=rejected, errors=errors)


# ──────────────────────────────────────────────
# GET /health
# ──────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Service health with per-store status and stale feed detection."""
    uptime = time.time() - _start_time
    warnings = []

    conn = get_database()
    try:
        # Get all stores that have events
        stores = conn.execute(
            """SELECT store_id, MAX(timestamp) as last_event,
                      COUNT(*) as event_count
               FROM events
               GROUP BY store_id"""
        ).fetchall()

        # Get today's event counts per store
        today_counts = conn.execute(
            """SELECT store_id, COUNT(*) as cnt
               FROM events
               WHERE date(timestamp) = date('now')
               GROUP BY store_id"""
        ).fetchall()
        today_map = {row["store_id"]: row["cnt"] for row in today_counts}

        store_health = {}
        for row in stores:
            store_id = row["store_id"]
            last_event = row["last_event"]
            event_count = row["event_count"]

            # Check for stale feed (>10 minutes since last event)
            status = "active"
            if last_event:
                try:
                    last_dt = datetime.fromisoformat(
                        last_event.replace("Z", "+00:00")
                    )
                    now = datetime.now(timezone.utc)
                    if (now - last_dt).total_seconds() > 600:
                        status = "stale"
                        warnings.append(
                            f"STALE_FEED: {store_id} last event {last_event}"
                        )
                except ValueError:
                    pass

            store_health[store_id] = StoreHealth(
                last_event_at=last_event,
                status=status,
                event_count_today=today_map.get(store_id, 0),
            )

        # If no stores have events yet, add the default store
        if not store_health:
            store_health["STORE_BLR_002"] = StoreHealth()

    finally:
        conn.close()

    overall_status = "healthy" if not warnings else "degraded"
    return HealthResponse(
        status=overall_status,
        uptime_seconds=round(uptime, 2),
        stores=store_health,
        warnings=warnings,
    )


# ──────────────────────────────────────────────
# GET /stores/{store_id}/metrics
# ──────────────────────────────────────────────

@app.get("/stores/{store_id}/metrics")
async def get_metrics(store_id: str):
    """
    Real-time store metrics.
    Full implementation in Subtask 7 — stub returning default values.
    """
    return {
        "store_id": store_id,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "unique_visitors": 0,
        "conversion_rate": 0.0,
        "avg_dwell_per_zone": {},
        "current_queue_depth": 0,
        "abandonment_rate": 0.0,
        "total_entries": 0,
        "total_exits": 0,
        "staff_excluded_count": 0,
    }


# ──────────────────────────────────────────────
# GET /stores/{store_id}/funnel
# ──────────────────────────────────────────────

@app.get("/stores/{store_id}/funnel")
async def get_funnel(store_id: str):
    """
    Conversion funnel stages.
    Full implementation in Subtask 7 — stub returning default values.
    """
    return {
        "store_id": store_id,
        "stages": [
            {"name": "ENTRY", "count": 0, "dropoff_pct": 0.0},
            {"name": "BROWSING", "count": 0, "dropoff_pct": 0.0},
            {"name": "BILLING", "count": 0, "dropoff_pct": 0.0},
            {"name": "CONVERSION", "count": 0, "dropoff_pct": 0.0},
        ],
        "overall_conversion": 0.0,
    }


# ──────────────────────────────────────────────
# GET /stores/{store_id}/heatmap
# ──────────────────────────────────────────────

@app.get("/stores/{store_id}/heatmap")
async def get_heatmap(store_id: str):
    """
    Zone heatmap data.
    Full implementation in Subtask 7 — stub returning default values.
    """
    return {
        "store_id": store_id,
        "zones": [
            {"zone_id": "ENTRY", "visit_count": 0, "avg_dwell_ms": 0, "score": 0},
            {"zone_id": "BROWSING", "visit_count": 0, "avg_dwell_ms": 0, "score": 0},
            {"zone_id": "BILLING", "visit_count": 0, "avg_dwell_ms": 0, "score": 0},
        ],
        "data_confidence": "low",
    }


# ──────────────────────────────────────────────
# GET /stores/{store_id}/anomalies
# ──────────────────────────────────────────────

@app.get("/stores/{store_id}/anomalies")
async def get_anomalies(store_id: str):
    """
    Anomaly detection results.
    Full implementation in Subtask 7 — stub returning empty list.
    """
    return {
        "store_id": store_id,
        "anomalies": [],
    }


# ──────────────────────────────────────────────
# GET /dashboard (serves HTML)
# ──────────────────────────────────────────────

@app.get("/dashboard")
async def get_dashboard():
    """Serve the web dashboard HTML."""
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)


# ──────────────────────────────────────────────
# Main (for direct execution)
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
