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
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse

from app.database import get_database, init_database, seed_pos_data
from app.models import (
    Anomaly,
    AnomalyResponse,
    EventBatch,
    FunnelResponse,
    FunnelStage,
    HealthResponse,
    HeatmapResponse,
    HeatmapZone,
    IngestResponse,
    MetricsResponse,
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

@app.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
async def get_metrics(store_id: str):
    """Real-time store metrics computed from live events."""
    conn = get_database()
    try:
        # Unique non-staff visitors
        visitors = conn.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt FROM events
               WHERE store_id = ? AND is_staff = 0""",
            (store_id,),
        ).fetchone()["cnt"]

        # Staff count
        staff_count = conn.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt FROM events
               WHERE store_id = ? AND is_staff = 1""",
            (store_id,),
        ).fetchone()["cnt"]

        # Total entries / exits
        total_entries = conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE store_id=? AND event_type='ENTRY'",
            (store_id,),
        ).fetchone()["cnt"]

        total_exits = conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE store_id=? AND event_type='EXIT'",
            (store_id,),
        ).fetchone()["cnt"]

        # Avg dwell per zone (from ZONE_DWELL events)
        dwell_rows = conn.execute(
            """SELECT zone_id, AVG(dwell_ms) as avg_dwell FROM events
               WHERE store_id=? AND event_type='ZONE_DWELL' AND zone_id IS NOT NULL
               GROUP BY zone_id""",
            (store_id,),
        ).fetchall()
        avg_dwell = {row["zone_id"]: int(row["avg_dwell"]) for row in dwell_rows}

        # Queue depth (latest BILLING_QUEUE_JOIN metadata)
        queue_row = conn.execute(
            """SELECT metadata_json FROM events
               WHERE store_id=? AND event_type='BILLING_QUEUE_JOIN'
               ORDER BY timestamp DESC LIMIT 1""",
            (store_id,),
        ).fetchone()
        queue_depth = 0
        if queue_row and queue_row["metadata_json"]:
            meta = json.loads(queue_row["metadata_json"])
            queue_depth = meta.get("queue_depth", 0)

        # Abandonment rate
        joins = conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE store_id=? AND event_type='BILLING_QUEUE_JOIN'",
            (store_id,),
        ).fetchone()["cnt"]
        abandons = conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE store_id=? AND event_type='BILLING_QUEUE_ABANDON'",
            (store_id,),
        ).fetchone()["cnt"]
        abandonment_rate = abandons / (joins + abandons) if (joins + abandons) > 0 else 0.0

        # Conversion rate — billing visitors with a POS transaction within 5 min
        billing_vids = [
            r["visitor_id"]
            for r in conn.execute(
                """SELECT DISTINCT visitor_id FROM events
                   WHERE store_id=? AND zone_id='BILLING' AND is_staff=0""",
                (store_id,),
            ).fetchall()
        ]

        pos_txns = conn.execute(
            "SELECT timestamp FROM pos_transactions WHERE store_id=?",
            (store_id,),
        ).fetchall()
        pos_times = [
            datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
            for r in pos_txns
        ]

        converted = 0
        for vid in billing_vids:
            billing_evts = conn.execute(
                """SELECT timestamp FROM events
                   WHERE store_id=? AND visitor_id=? AND zone_id='BILLING'
                   AND event_type IN ('ZONE_ENTER','ZONE_DWELL')""",
                (store_id, vid),
            ).fetchall()
            for be in billing_evts:
                bev_time = datetime.fromisoformat(be["timestamp"].replace("Z", "+00:00"))
                found = False
                for pt in pos_times:
                    if 0 <= (pt - bev_time).total_seconds() <= 300:
                        converted += 1
                        found = True
                        break
                if found:
                    break

        conversion_rate = converted / visitors if visitors > 0 else 0.0

        return MetricsResponse(
            store_id=store_id,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            unique_visitors=visitors,
            conversion_rate=round(conversion_rate, 3),
            avg_dwell_per_zone=avg_dwell,
            current_queue_depth=queue_depth,
            abandonment_rate=round(abandonment_rate, 3),
            total_entries=total_entries,
            total_exits=total_exits,
            staff_excluded_count=staff_count,
        )
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /stores/{store_id}/funnel
# ──────────────────────────────────────────────

@app.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def get_funnel(store_id: str):
    """Conversion funnel: Entry → Zone Visit → Billing Queue → Purchase."""
    conn = get_database()
    try:
        # Stage 1: Entry (unique non-staff visitors who entered)
        entries = conn.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt FROM events
               WHERE store_id=? AND event_type='ENTRY' AND is_staff=0""",
            (store_id,),
        ).fetchone()["cnt"]

        # Stage 2: Zone Visit (visited a product zone)
        zone_visits = conn.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt FROM events
               WHERE store_id=? AND event_type='ZONE_ENTER'
               AND zone_id IN ('SKINCARE','MAKEUP','BROWSING') AND is_staff=0""",
            (store_id,),
        ).fetchone()["cnt"]

        # Stage 3: Billing Queue (joined billing queue)
        billing_queue = conn.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt FROM events
               WHERE store_id=? AND event_type='BILLING_QUEUE_JOIN' AND is_staff=0""",
            (store_id,),
        ).fetchone()["cnt"]

        # Stage 4: Purchase (converted — billing visitor + POS txn within 5 min)
        billing_vids = [
            r["visitor_id"]
            for r in conn.execute(
                """SELECT DISTINCT visitor_id FROM events
                   WHERE store_id=? AND zone_id='BILLING' AND is_staff=0""",
                (store_id,),
            ).fetchall()
        ]

        pos_txns = conn.execute(
            "SELECT timestamp FROM pos_transactions WHERE store_id=?",
            (store_id,),
        ).fetchall()
        pos_times = [
            datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
            for r in pos_txns
        ]

        purchase = 0
        for vid in billing_vids:
            billing_evts = conn.execute(
                """SELECT timestamp FROM events
                   WHERE store_id=? AND visitor_id=? AND zone_id='BILLING'
                   AND event_type IN ('ZONE_ENTER','ZONE_DWELL')""",
                (store_id, vid),
            ).fetchall()
            for be in billing_evts:
                bev_time = datetime.fromisoformat(be["timestamp"].replace("Z", "+00:00"))
                found = False
                for pt in pos_times:
                    if 0 <= (pt - bev_time).total_seconds() <= 300:
                        purchase += 1
                        found = True
                        break
                if found:
                    break

        stages = [
            FunnelStage(name="Entry", count=entries, dropoff_pct=0.0),
            FunnelStage(
                name="Zone Visit",
                count=zone_visits,
                dropoff_pct=round(max(0.0, (1 - zone_visits / entries) * 100), 1)
                if entries > 0
                else 0.0,
            ),
            FunnelStage(
                name="Billing Queue",
                count=billing_queue,
                dropoff_pct=round(max(0.0, (1 - billing_queue / zone_visits) * 100), 1)
                if zone_visits > 0
                else 0.0,
            ),
            FunnelStage(
                name="Purchase",
                count=purchase,
                dropoff_pct=round(max(0.0, (1 - purchase / billing_queue) * 100), 1)
                if billing_queue > 0
                else 0.0,
            ),
        ]

        overall_conversion = purchase / entries if entries > 0 else 0.0

        return FunnelResponse(
            store_id=store_id,
            stages=stages,
            overall_conversion=round(overall_conversion, 3),
        )
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /stores/{store_id}/heatmap
# ──────────────────────────────────────────────

@app.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
async def get_heatmap(store_id: str):
    """Zone heatmap with visit counts, average dwell, and activity score (0–100)."""
    conn = get_database()
    try:
        zones_data = conn.execute(
            """SELECT zone_id, COUNT(DISTINCT visitor_id) as visits,
                      AVG(dwell_ms) as avg_dwell
               FROM events
               WHERE store_id=? AND event_type='ZONE_ENTER' AND zone_id IS NOT NULL
               GROUP BY zone_id""",
            (store_id,),
        ).fetchall()

        # Score is proportional to visit count relative to the busiest zone
        max_visits = max((z["visits"] for z in zones_data), default=1) or 1

        zones = []
        for z in zones_data:
            score = int((z["visits"] / max_visits) * 100)
            zones.append(
                HeatmapZone(
                    zone_id=z["zone_id"],
                    visit_count=z["visits"],
                    avg_dwell_ms=int(z["avg_dwell"] or 0),
                    score=score,
                )
            )

        # Data confidence based on total sessions
        total_sessions = conn.execute(
            "SELECT COUNT(DISTINCT visitor_id) as cnt FROM events WHERE store_id=?",
            (store_id,),
        ).fetchone()["cnt"]
        confidence = (
            "high" if total_sessions >= 20 else "medium" if total_sessions >= 10 else "low"
        )

        return HeatmapResponse(
            store_id=store_id,
            zones=zones,
            data_confidence=confidence,
        )
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /stores/{store_id}/anomalies
# ──────────────────────────────────────────────

@app.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
async def get_anomalies(store_id: str):
    """Detect anomalies: billing queue spikes, conversion drops, dead zones."""
    conn = get_database()
    try:
        anomalies = []

        # ── BILLING_QUEUE_SPIKE ──
        queue_row = conn.execute(
            """SELECT metadata_json FROM events
               WHERE store_id=? AND event_type='BILLING_QUEUE_JOIN'
               ORDER BY timestamp DESC LIMIT 1""",
            (store_id,),
        ).fetchone()
        if queue_row and queue_row["metadata_json"]:
            meta = json.loads(queue_row["metadata_json"])
            qd = meta.get("queue_depth", 0)
            if qd > 6:
                anomalies.append(
                    Anomaly(
                        type="BILLING_QUEUE_SPIKE",
                        severity="WARN",
                        description=(
                            f"Queue depth {qd} exceeds normal threshold of 6"
                        ),
                        detected_at=datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        suggested_action="Open additional billing counter",
                    )
                )

        # ── CONVERSION_DROP ──
        visitors = conn.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt FROM events
               WHERE store_id=? AND is_staff=0""",
            (store_id,),
        ).fetchone()["cnt"]

        if visitors > 0:
            billing_vids = [
                r["visitor_id"]
                for r in conn.execute(
                    """SELECT DISTINCT visitor_id FROM events
                       WHERE store_id=? AND zone_id='BILLING' AND is_staff=0""",
                    (store_id,),
                ).fetchall()
            ]

            pos_txns = conn.execute(
                "SELECT timestamp FROM pos_transactions WHERE store_id=?",
                (store_id,),
            ).fetchall()
            pos_times = [
                datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
                for r in pos_txns
            ]

            converted = 0
            for vid in billing_vids:
                billing_evts = conn.execute(
                    """SELECT timestamp FROM events
                       WHERE store_id=? AND visitor_id=? AND zone_id='BILLING'
                       AND event_type IN ('ZONE_ENTER','ZONE_DWELL')""",
                    (store_id, vid),
                ).fetchall()
                for be in billing_evts:
                    bev_time = datetime.fromisoformat(
                        be["timestamp"].replace("Z", "+00:00")
                    )
                    found = False
                    for pt in pos_times:
                        if 0 <= (pt - bev_time).total_seconds() <= 300:
                            converted += 1
                            found = True
                            break
                    if found:
                        break

            conv_rate = converted / visitors
            if conv_rate < 0.1:
                anomalies.append(
                    Anomaly(
                        type="CONVERSION_DROP",
                        severity="WARN",
                        description=(
                            f"Conversion rate {conv_rate:.1%} is below 10% threshold"
                        ),
                        detected_at=datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        suggested_action="Investigate floor staffing and queue management",
                    )
                )

        # ── DEAD_ZONE ──
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
        dead_zones = conn.execute(
            """SELECT zone_id FROM events
               WHERE store_id=? AND event_type='ZONE_ENTER'
               GROUP BY zone_id
               HAVING MAX(timestamp) < ?""",
            (store_id, threshold),
        ).fetchall()

        for row in dead_zones:
            anomalies.append(
                Anomaly(
                    type="DEAD_ZONE",
                    severity="INFO",
                    description=f"Zone {row['zone_id']} has had no visitors in the last 30 minutes",
                    detected_at=datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    suggested_action="Check if zone is staffed and stocked",
                )
            )

        return AnomalyResponse(store_id=store_id, anomalies=anomalies)
    finally:
        conn.close()


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
