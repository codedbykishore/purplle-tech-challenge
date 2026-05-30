# Winning Plan — Purplle Tech Challenge 2026 Round 2

## Executive Summary

Build an end-to-end Store Intelligence system: raw CCTV footage → structured events → real-time analytics API. Target **85+ score** (Strong Candidate tier) by prioritizing: **working system > edge case handling > documentation quality > dashboard bonus**.

**Total points available:** 100 + 10 bonus = 110
**Target score breakdown:**
| Part | Max | Target |
|------|-----|--------|
| A: Detection Pipeline | 30 | 25 |
| B: Intelligence API | 35 | 30 |
| C: Production Readiness | 20 | 18 |
| D: AI Engineering | 15 | 13 |
| E: Live Dashboard | +10 | +8 |
| **Total** | **110** | **94** |

---

## Phase 0: Foundation (Hours 0-2)

### 0.1 Environment Setup
```bash
# Verify dataset is available
ls docs/
# Should see: CCTV footage zip, store_layout.json, pos_transactions.csv,
# sample_events.jsonl, assertions.py

# Create project structure immediately
mkdir -p pipeline/ app/ tests/ docs/
```

### 0.2 Analyze Provided Data (Critical First Step)
1. **Unzip CCTV footage** — identify all 5 stores × 3 cameras × 20min clips
2. **Parse `store_layout.json`** — extract zone definitions, camera coverage mappings, open hours per store
3. **Parse `pos_transactions.csv`** — understand schema, date range, store IDs, transaction volumes
4. **Parse `sample_events.jsonl`** — reverse-engineer the expected event schema precisely (200 examples = your ground truth for validation)
5. **Run `assertions.py`** — understand the 10 test cases your API must pass

### 0.3 Key Data Structure Decisions
- **Store IDs:** 5 stores (e.g., `STORE_BLR_002` based on POS data)
- **Camera IDs:** 3 per store — `CAM_ENTRY_01`, `CAM_MAIN_01`, `CAM_BILLING_01`
- **Zones from store_layout.json:** Map zone names to camera coverage polygons
- **POS correlation window:** 5-minute window before transaction timestamp

---

## Phase 1: Detection Pipeline (Hours 2-16) — 30 Points

### Architecture Decision: YOLOv8 + ByteTrack + Distance-based Re-ID

**Why YOLOv8:**
- Best speed/accuracy tradeoff for 1080p@15fps CCTV
- Pre-trained on COCO (person class = class 0)
- Easy to containerize (ultralytics package)
- Excellent community support and edge case handling

**Why ByteTrack:**
- Handles occlusion better than DeepSORT
- Works with low-frame-rate CCTV (15fps)
- No re-identification model needed — uses motion + appearance

**Why distance-based Re-ID (not OSNet):**
- Faces are blurred — appearance-based Re-ID is unreliable
- Bounding box trajectory + entry/exit zone matching is sufficient
- Simpler, faster, and more robust for this specific scenario

### 1.1 Detection Script (`pipeline/detect.py`)

```
Pipeline Flow:
Video Clip → YOLOv8 (person detection) → ByteTrack (tracking)
    → Zone Classification (polygon intersection)
    → Staff Detection (uniform color analysis)
    → Event Emission (JSONL output)
```

**Key Implementation Details:**

#### Person Detection
- Use `yolov8m.pt` (medium model) — good balance of speed/accuracy
- Confidence threshold: 0.35 (catch partial occlusions, don't suppress low-conf)
- Input: 1080p frames downscaled to 640 for inference, map back to original coords
- Process every 2nd frame (7.5 effective fps) to manage compute while maintaining tracking continuity

#### Tracking (ByteTrack)
- `track_thresh`: 0.35 (match detection threshold)
- `high_thresh`: 0.6 (confirmed track threshold)
- `match_thresh`: 0.8 (association threshold)
- `track_buffer`: 60 frames (4 seconds at 15fps — handle brief occlusions)
- Each track gets a persistent `track_id` within a clip

#### Entry/Exit Detection
- Define entry zone as a polygon from `store_layout.json` entry camera coverage
- **Direction logic:** Track the centroid of each person's bounding box over time
  - Moving INTO the store (centroid moving away from door, toward interior) → `ENTRY`
  - Moving OUT OF the store (centroid moving toward door, away from interior) → `EXIT`
- Use velocity vector over 15 frames (1 second) to determine direction
- **Threshold:** Person's bottom-center must cross the entry line (defined in store_layout.json)

#### Zone Classification
- Load zone polygons from `store_layout.json`
- For each frame, check if person's bottom-center point is inside any zone polygon
- Use `shapely.geometry.Point` for point-in-polygon tests
- Zone transitions emit `ZONE_ENTER` / `ZONE_EXIT` events
- `ZONE_DWELL` emitted every 30 seconds of continuous zone presence

#### Visitor ID Assignment (Re-ID)
- **Within a single clip:** Use ByteTrack's persistent `track_id` directly
- **Across cameras (same store):** Use entry/exit zone + time window matching
  - If camera_entry and camera_main detect the same person (by bounding box overlap when both cameras see the person) → same visitor_id
  - **Practical approach:** Process entry camera first, assign visitor_ids. For main floor camera, match by spatial position in overlapping zones + time proximity
- **Re-entry detection:** If a visitor exits (EXIT event) and then a new person enters within 5 minutes from the same direction with similar appearance → assign same visitor_id, emit REENTRY event
- **Visitor ID format:** `VIS_` + first 6 chars of UUID5(store_id + entry_time)

#### Staff Detection
- **Primary method:** Check if person is in frame > 30 minutes (staff stay long)
- **Secondary method:** Uniform color detection — sample average color of person's upper body bounding box region, compare against known uniform colors (if identifiable from store_layout.json or by running a VLM on a sample frame)
- **Fallback:** If a person appears in > 3 different zones with high mobility → likely staff
- **VLM approach (if needed):** Send a sample frame to GPT-4V/Claude Vision with prompt: "Identify which people in this frame appear to be store staff vs customers based on clothing and behavior." Document the prompt in DESIGN.md.
- Set `is_staff: true` and exclude from customer metrics

#### Group Handling
- When 3 people enter simultaneously through the entry camera:
  - ByteTrack assigns 3 separate `track_id`s
  - Pipeline emits 3 separate ENTRY events
  - Each gets its own visitor_id
- **Key:** ByteTrack naturally handles this — multiple persons detected in same frame get individual tracks

#### Confidence Calibration
- Pass through raw YOLOv8 confidence scores — do NOT suppress low-confidence detections
- Log confidence distribution for debugging
- Flag detections with confidence < 0.3 as low-quality in metadata

### 1.2 Event Schema Implementation (`pipeline/emit.py`)

```python
# Event schema — must match problem statement exactly
event = {
    "event_id": str(uuid4()),          # globally unique
    "store_id": store_id,              # from store_layout.json
    "camera_id": camera_id,            # CAM_ENTRY_01, CAM_MAIN_01, CAM_BILLING_01
    "visitor_id": visitor_id,           # VIS_xxxxx format
    "event_type": event_type,           # ENTRY/EXIT/ZONE_ENTER/ZONE_EXIT/ZONE_DWELL/etc.
    "timestamp": iso8601_utc,          # clip_start_time + (frame_number / fps)
    "zone_id": zone_id,                # null for ENTRY/EXIT
    "dwell_ms": dwell_duration_ms,     # 0 for instantaneous events
    "is_staff": is_staff_bool,         # your classification
    "confidence": yolo_confidence,     # raw detection confidence
    "metadata": {
        "queue_depth": queue_depth,     # integer for BILLING_QUEUE_JOIN
        "sku_zone": zone_label,         # from store_layout.json
        "session_seq": sequence_num     # ordinal position in session
    }
}
```

**Event Type Emission Rules:**
| Event | Trigger | Key Logic |
|-------|---------|-----------|
| ENTRY | Person crosses entry threshold inbound | New visitor_id assigned |
| EXIT | Person crosses entry threshold outbound | Close session |
| ZONE_ENTER | Person enters named zone polygon | From store_layout.json |
| ZONE_EXIT | Person leaves named zone polygon | |
| ZONE_DWELL | In zone continuously for 30+ sec | Emit every 30s |
| BILLING_QUEUE_JOIN | Enters billing zone while queue_depth > 0 | Count people in billing zone |
| BILLING_QUEUE_ABANDON | Leaves billing zone before POS txn | Time window correlation |
| REENTRY | Same visitor_id after prior EXIT | Re-ID match |

### 1.3 Pipeline Runner (`pipeline/run.sh`)

```bash
#!/bin/bash
# Process all clips and emit events to JSONL
# Usage: ./pipeline/run.sh <clips_dir> <output_file>

CLIPS_DIR=${1:-./data/clips}
OUTPUT=${2:-./data/events.jsonl}

python pipeline/detect.py \
  --clips-dir "$CLIPS_DIR" \
  --store-layout ./data/store_layout.json \
  --output "$OUTPUT" \
  --model yolov8m \
  --conf-threshold 0.35
```

### 1.4 Handling Edge Cases (Critical for Scoring)

| Edge Case | Solution |
|-----------|----------|
| **Group entry (2-4 people)** | ByteTrack assigns individual tracks per person; emit one ENTRY per track_id |
| **Staff movement** | Staff detection via duration + uniform analysis; set is_staff=true |
| **Re-entry** | Match exiting visitor_id to re-entering person by trajectory + time window (<5min gap) |
| **Partial occlusion** | YOLOv8 handles partial occlusion well; lower confidence threshold to 0.35; don't suppress low-conf |
| **Billing queue buildup** | Count people in billing zone polygon; emit BILLING_QUEUE_JOIN when count > 0; track queue_depth |
| **Empty store periods** | Pipeline handles gracefully — no events emitted, API returns zero metrics |
| **Camera overlap** | Spatial matching in overlapping zones + time proximity to avoid double-counting |
| **POS correlation** | 5-minute window: visitor in billing zone within 5min of POS transaction = converted |

### 1.5 Validation Strategy

1. **Run pipeline on 1 clip per store** — compare approximate entry/exit counts manually
2. **Validate against `sample_events.jsonl`** — check schema compliance, event_id uniqueness, timestamp correctness
3. **Run `assertions.py`** — ensure 10 test assertions pass
4. **Check edge cases specifically:**
   - Do groups produce multiple ENTRY events?
   - Are staff flagged correctly?
   - Does re-entry produce REENTRY (not duplicate ENTRY)?
   - Is queue_depth populated for BILLING_QUEUE_JOIN?

---

## Phase 2: Intelligence API (Hours 16-30) — 35 Points

### Architecture: FastAPI + SQLite + Background Ingestion

**Why FastAPI:** Best Python API framework, automatic OpenAPI docs, async support, type validation with Pydantic
**Why SQLite:** Simple, file-based, no external dependencies, sufficient for this scale, easy to containerize

### 2.1 API Structure (`app/`)

```
app/
├── main.py          # FastAPI app, middleware, CORS
├── models.py        # Pydantic schemas for events, responses
├── database.py      # SQLite connection, table creation
├── ingestion.py     # POST /events/ingest logic
├── metrics.py       # GET /stores/{id}/metrics
├── funnel.py        # GET /stores/{id}/funnel
├── heatmap.py       # GET /stores/{id}/heatmap
├── anomalies.py     # GET /stores/{id}/anomalies
├── health.py        # GET /health
└── session.py       # Session management, visitor dedup
```

### 2.2 Database Schema

```sql
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    visitor_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,  -- ISO-8601 UTC
    zone_id TEXT,
    dwell_ms INTEGER DEFAULT 0,
    is_staff BOOLEAN DEFAULT FALSE,
    confidence REAL DEFAULT 0.0,
    metadata_json TEXT,  -- JSON string
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_store ON events(store_id);
CREATE INDEX idx_events_timestamp ON events(timestamp);
CREATE INDEX idx_events_visitor ON events(visitor_id);
CREATE INDEX idx_events_type ON events(event_type);

CREATE TABLE pos_transactions (
    store_id TEXT NOT NULL,
    transaction_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    basket_value_inr REAL NOT NULL
);

CREATE INDEX idx_pos_store ON pos_transactions(store_id);
CREATE INDEX idx_pos_timestamp ON pos_transactions(timestamp);
```

### 2.3 Endpoint Implementations

#### POST /events/ingest
- Accept batch of up to 500 events
- Validate each event against Pydantic schema
- Deduplicate by `event_id` (idempotent)
- Partial success: return `{"accepted": 498, "rejected": 2, "errors": [...]}`
- Store in SQLite
- Structured error response for malformed events

#### GET /stores/{id}/metrics
```python
# Response schema:
{
    "store_id": "STORE_BLR_002",
    "date": "2026-03-03",
    "unique_visitors": 42,
    "conversion_rate": 0.357,  # 15/42
    "avg_dwell_per_zone": {"SKINCARE": 180000, "MAKEUP": 240000, ...},
    "current_queue_depth": 3,
    "abandonment_rate": 0.15,
    "total_entries": 48,
    "total_exits": 45,
    "staff_excluded_count": 6
}
```

**Key logic:**
- Exclude `is_staff=true` events
- Unique visitors = count distinct `visitor_id` where `event_type=ENTRY`
- Conversion rate = visitors with ZONE_ENTER(BILLING) + matching POS txn / total visitors
- Handle zero-traffic stores: return zeros, not null

#### GET /stores/{id}/funnel
```python
# Funnel stages with session-based counting:
{
    "store_id": "STORE_BLR_002",
    "stages": [
        {"name": "Entry", "count": 42, "dropoff_pct": 0.0},
        {"name": "Zone Visit", "count": 38, "dropoff_pct": 9.5},
        {"name": "Billing Queue", "count": 22, "dropoff_pct": 42.1},
        {"name": "Purchase", "count": 15, "dropoff_pct": 31.8}
    ],
    "overall_conversion": 0.357
}
```

**Key logic:**
- Session is the unit — a visitor enters once, may visit multiple zones
- Re-entries must NOT double-count (same visitor_id = same session)
- Zone Visit = any ZONE_ENTER event (excluding ENTRY/EXIT zones)
- Billing Queue = BILLING_QUEUE_JOIN event
- Purchase = POS transaction correlated within 5-minute window

#### GET /stores/{id}/heatmap
```python
# Zone visit frequency + avg dwell, normalized 0-100
{
    "store_id": "STORE_BLR_002",
    "zones": [
        {"zone_id": "SKINCARE", "visit_count": 35, "avg_dwell_ms": 180000, "score": 85},
        {"zone_id": "MAKEUP", "visit_count": 42, "avg_dwell_ms": 120000, "score": 100},
        {"zone_id": "BILLING", "visit_count": 22, "avg_dwell_ms": 60000, "score": 52}
    ],
    "data_confidence": "high"  # "low" if < 20 sessions in window
}
```

#### GET /stores/{id}/anomalies
```python
# Active anomalies with severity
{
    "store_id": "STORE_BLR_002",
    "anomalies": [
        {
            "type": "BILLING_QUEUE_SPIKE",
            "severity": "WARN",
            "description": "Queue depth 8 exceeds normal threshold of 4",
            "detected_at": "2026-03-03T14:35:00Z",
            "suggested_action": "Open additional billing counter"
        },
        {
            "type": "CONVERSION_DROP",
            "severity": "CRITICAL",
            "description": "Current conversion 15% vs 7-day avg 35%",
            "detected_at": "2026-03-03T14:30:00Z",
            "suggested_action": "Investigate store conditions, check staff availability"
        }
    ]
}
```

**Anomaly detection logic:**
- **BILLING_QUEUE_SPIKE:** queue_depth > 2× rolling average (or > 6 absolute)
- **CONVERSION_DROP:** current conversion < 50% of 7-day average
- **DEAD_ZONE:** zone with no ZONE_ENTER events in 30 minutes
- Severity: INFO / WARN / CRITICAL with thresholds

#### GET /health
```python
{
    "status": "healthy",
    "uptime_seconds": 3600,
    "stores": {
        "STORE_BLR_002": {
            "last_event_at": "2026-03-03T14:38:12Z",
            "status": "active",
            "event_count_today": 245
        }
    },
    "warnings": []
}
```
- STALE_FEED warning if > 10 minutes since last event for a store

### 2.4 Session Management (`app/session.py`)

This is the most critical piece for accuracy:

```python
class SessionManager:
    """
    Groups events into visitor sessions.
    A session = one ENTRY → one EXIT.
    Re-entries within time window = same session (REENTRY event).
    """
    
    def create_session(self, visitor_id, entry_event):
        # New session with entry timestamp
        
    def check_reentry(self, visitor_id, entry_event, time_window_minutes=5):
        # If visitor exited < time_window_minutes ago → REENTRY
        # Same visitor_id, extends existing session
        
    def close_session(self, visitor_id, exit_event):
        # Close session, compute final metrics
        
    def is_converted(self, visitor_id, pos_transactions, window_minutes=5):
        # Check if visitor was in billing zone within window of any POS txn
```

### 2.5 POS Correlation Logic

```python
def correlate_visitor_conversion(visitor_id, store_id, events, pos_transactions):
    """
    A visitor who was in the billing zone in the 5-minute window
    before a transaction timestamp counts as converted.
    """
    # Get all billing zone events for this visitor
    billing_events = [e for e in events 
                      if e.visitor_id == visitor_id 
                      and e.zone_id == "BILLING"
                      and e.event_type in ("ZONE_ENTER", "ZONE_DWELL")]
    
    # Get POS transactions for this store in the relevant time range
    store_pos = [t for t in pos_transactions if t.store_id == store_id]
    
    for txn in store_pos:
        txn_time = parse_timestamp(txn.timestamp)
        for bev in billing_events:
            bev_time = parse_timestamp(bev.timestamp)
            if 0 <= (txn_time - bev_time).total_seconds() <= 300:
                return True  # Converted
    return False
```

---

## Phase 3: Production Readiness (Hours 30-38) — 20 Points

### 3.1 Docker Configuration

**`Dockerfile` (API):**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY data/ ./data/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`Dockerfile` (Pipeline):**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pipeline/ ./pipeline/
COPY data/ ./data/
CMD ["python", "pipeline/detect.py", "--clips-dir", "./data/clips", "--output", "./data/events.jsonl"]
```

**`docker-compose.yml`:**
```yaml
version: '3.8'
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - DATABASE_PATH=/app/data/store_intelligence.db
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  pipeline:
    build:
      context: .
      dockerfile: Dockerfile.pipeline
    volumes:
      - ./data:/app/data
    depends_on:
      - api
    # Can be run manually: docker compose run pipeline
```

### 3.2 Structured Logging

```python
import structlog

logger = structlog.get_logger()

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    trace_id = str(uuid4())
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
        event_count=getattr(request.state, "event_count", None)
    )
    return response
```

### 3.3 Graceful Degradation

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("unhandled_exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=503,
        content={
            "error": "service_unavailable",
            "message": "An internal error occurred",
            "trace_id": str(uuid4())
        }
    )

# Database unavailable check
@app.middleware("http")
async def db_health_check(request: Request, call_next):
    try:
        db = get_database()
        db.execute("SELECT 1")
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"error": "database_unavailable", "message": "Database connection failed"}
        )
    return await call_next(request)
```

### 3.4 Test Suite (`tests/`)

**Target: >70% statement coverage + edge cases**

```python
# tests/test_pipeline.py
# PROMPT: "Generate test cases for a CCTV detection pipeline that processes video clips
# and emits structured events. Test: schema validation, event_id uniqueness, timestamp
# correctness, staff detection, group entry handling, re-entry detection, zero-traffic
# handling, and POS correlation. Use pytest with fixtures."
# CHANGES MADE: Added edge cases for partial occlusion and empty store periods.
# Adjusted confidence threshold assertions. Added billing queue depth validation.

# tests/test_metrics.py
# PROMPT: "Generate test cases for a store metrics API endpoint. Test: unique visitor
# counting, conversion rate calculation, staff exclusion, zero-purchase stores,
# real-time metrics (not cached), and zone dwell computation. Use httpx AsyncClient
# with FastAPI TestClient pattern."
# CHANGES MADE: Added test for re-entry not double-counting. Added test for
# empty store returning zeros instead of null. Added test for stale feed warning.

# tests/test_anomalies.py
# PROMPT: "Generate test cases for anomaly detection in retail analytics. Test:
# queue spike detection, conversion drop detection, dead zone detection,
# severity levels (INFO/WARN/CRITICAL), and suggested_action strings."
# CHANGES MADE: Added test for edge case where all zones are dead. Added
# test for normal conditions returning empty anomaly list.
```

**Critical test cases (must cover):**
1. Empty store — returns zero metrics, no crashes
2. All-staff clip — all visitors flagged as staff, customer metrics = 0
3. Zero purchases — conversion rate = 0, no division by zero
4. Re-entry in funnel — same visitor counted once, not twice
5. Batch ingest with duplicate event_ids — idempotent, no duplicates
6. Malformed event in batch — partial success, structured error
7. Database unavailable — HTTP 503 with structured body
8. Stale feed (>10 min lag) — warning in /health response
9. Queue buildup and abandonment — correct queue_depth tracking
10. POS correlation within 5-minute window — conversion correctly attributed

### 3.5 README.md

```markdown
# Store Intelligence API — Apex Retail

## Quick Start (5 commands)
git clone <repo-url>
cd store-intelligence
docker compose up --build

# In another terminal, run detection pipeline:
docker compose run pipeline

# API is now available at http://localhost:8000
# Docs at http://localhost:8000/docs

## Architecture
[Brief description with diagram]

## Running Detection Pipeline
[Step-by-step instructions for processing CCTV clips]

## API Endpoints
[Table of endpoints with descriptions]

## Design Decisions
See DESIGN.md and CHOICES.md
```

---

## Phase 4: AI Engineering Documentation (Hours 38-42) — 15 Points

### 4.1 DESIGN.md (~500-700 words)

```
# Architecture Overview
[Describe the 4-stage pipeline visually and functionally]

# Detection Pipeline
[YOLOv8 → ByteTrack → Zone Classification → Event Emission]

# Intelligence API
[FastAPI → SQLite → Real-time Metrics]

# Data Flow
[CCTV → Pipeline → Events → API → Dashboard]

# AI-Assisted Decisions (REQUIRED SECTION)
## 1. Detection Model Selection
AI suggested YOLOv8 over YOLOv9 for better ecosystem support.
I agreed — ultralytics package is production-ready with better docs.

## 2. Staff Detection Approach
AI suggested using a VLM for staff classification. I tried it and found
it works for sample frames but is too slow for batch processing.
I overrode with a hybrid approach: duration-based + color analysis.

## 3. Zone Classification
AI suggested using VLM for zone classification. I found polygon-based
point-in-polygon is faster and more reliable for fixed camera setups.
I overrode — VLM adds latency with no accuracy gain.

# Edge Case Handling
[Detailed explanation of how each edge case is addressed]

# Trade-offs
[What you chose and what you gave up]
```

### 4.2 CHOICES.md (~500-700 words)

**Decision 1: Detection Model**
- Options: YOLOv8, YOLOv9, RT-DETR, MediaPipe
- AI suggested: YOLOv8 (best ecosystem, proven for person detection)
- What AI didn't consider: YOLOv9 has better accuracy on small objects but worse docs
- My choice: YOLOv8m — proven, well-documented, sufficient accuracy for retail CCTV
- Why: 48-hour window favors battle-tested tools over marginally better alternatives

**Decision 2: Event Schema Design**
- Options: Flat schema, nested schema, event-sourced schema
- AI suggested: Flat schema with metadata object (as specified)
- What AI didn't consider: The metadata object allows extension without schema changes
- My choice: Follow the exact schema from problem statement, add metadata for flexibility
- Why: Schema compliance is a scoring criterion — no deviation from spec

**Decision 3: API Architecture**
- Options: FastAPI + SQLite, FastAPI + PostgreSQL, Flask + Redis
- AI suggested: FastAPI + PostgreSQL for production-readiness
- What AI didn't consider: Docker compose simplicity and no external service dependencies
- My choice: FastAPI + SQLite (with WAL mode for concurrent reads)
- Why: Simpler deployment, still production-aware, easy to swap to PostgreSQL later

---

## Phase 5: Live Dashboard (Hours 42-46) — +10 Bonus Points

### 5.1 Terminal Dashboard (Simpler, Guaranteed to Work)

```python
# app/dashboard.py
from rich.live import Live
from rich.table import Table
from rich.console import Console

def render_dashboard(store_id: str):
    """Terminal dashboard showing live metrics updating from event stream."""
    table = Table(title=f"Store Intelligence — {store_id}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    # Poll API every 5 seconds
    while True:
        metrics = fetch_metrics(store_id)
        table.add_row("Unique Visitors", str(metrics["unique_visitors"]))
        table.add_row("Conversion Rate", f"{metrics['conversion_rate']:.1%}")
        table.add_row("Queue Depth", str(metrics["current_queue_depth"]))
        table.add_row("Avg Dwell (min)", f"{metrics['avg_dwell_total_ms']/60000:.1f}")
        
        with Live(table, refresh_per_second=1) as live:
            live.update(table)
        
        time.sleep(5)
```

### 5.2 Web Dashboard (Higher Score)

```python
# Simple HTML + JavaScript dashboard
# GET /dashboard serves a page that polls /stores/{id}/metrics every 5 seconds
# Uses Chart.js for visualization
# Shows: visitor count, conversion rate, queue depth, zone heatmap
```

**Recommendation:** Build terminal dashboard first (guaranteed bonus), add web UI if time permits.

---

## Timeline & Priority Matrix

| Phase | Hours | Priority | Points | Risk |
|-------|-------|----------|--------|------|
| 0: Foundation | 0-2 | CRITICAL | 0 | Low |
| 1: Detection Pipeline | 2-16 | CRITICAL | 30 | HIGH — most time, most scoring |
| 2: Intelligence API | 16-30 | CRITICAL | 35 | Medium — well-defined endpoints |
| 3: Production Readiness | 30-38 | HIGH | 20 | Low — standard practices |
| 4: AI Documentation | 38-42 | HIGH | 15 | Low — writing task |
| 5: Live Dashboard | 42-46 | MEDIUM | +10 | Low — bonus, terminal first |

### Time Buffer
- Total: 46 hours of work in 48-hour window
- 2 hours buffer for debugging, testing, final polish

---

## Critical Success Factors

1. **Get detection working first** — everything downstream depends on it
2. **Validate against sample_events.jsonl** — your ground truth for schema compliance
3. **Test the acceptance gate early** — `docker compose up`, `POST /events/ingest`, `GET /metrics`
4. **Don't chase perfection** — 80% detection accuracy with solid API > 95% detection with broken API
5. **Document everything** — follow-up questions require deep understanding of your choices
6. **Handle zero-traffic gracefully** — empty stores are a stated edge case
7. **Idempotent ingest** — this is explicitly tested and scored
8. **Real-time, not cached** — metrics must reflect current state, not yesterday's data

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| YOLOv8 too slow for batch processing | Process every 2nd frame, use GPU if available |
| Re-ID fails across cameras | Fallback to time-window + zone-based matching |
| SQLite lock contention | Use WAL mode, connection pooling |
| Docker build fails | Test docker compose up on clean machine before submission |
| Edge cases not handled | Reference the 7 edge cases in problem statement, test each explicitly |
| Time runs out | Prioritize Part A + B (65 points) over Part D + E (25 points) |
