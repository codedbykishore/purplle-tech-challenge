# Final Plan v3 — Purplle Tech Challenge 2026 Round 2

## Executive Summary

End-to-end Store Intelligence system: raw CCTV footage → structured events → real-time analytics API + web dashboard. 

**Target: 91-97/110** (well above 85 "Strong Candidate" threshold).

**Score breakdown:**
| Part | Max | Target |
|------|-----|--------|
| A: Detection Pipeline | 30 | 25 |
| B: Intelligence API | 35 | 32 |
| C: Production Readiness | 20 | 18 |
| D: AI Engineering | 15 | 14 |
| E: Live Dashboard | +10 | +9 |
| **Total** | **110** | **91-97** |

---

## What Was Rejected (and Why)

16 proposals were evaluated and dropped. None are in this plan.

| Proposal | Why It's Gone |
|----------|---------------|
| RT-DETR replacing YOLOv8 | Installation risk dwarfs ~0.3 point gain |
| BoT-SORT + OSNet Re-ID | Faces blurred — appearance embedding degrades to clothing color |
| CLIP staff detection | 54K calls at ~500ms each = 7.5 hours CPU |
| Multi-camera homography | No calibration data, error exceeds zone-overlap matching |
| SKU-level POS integration | No customer ID in POS data |
| Inventory alerting | No inventory data in dataset |
| Slack/webhooks | Scoring harness runs isolated Docker — webhooks fail silently |
| Prophet forecasting | 20-minute clips, Prophet needs months of data |
| k-means journey clustering | 30-50 visitors, arbitrary boundaries, not in API spec |
| Staff optimization engine | Requires causal model + A/B test data |
| Layout A/B testing | No layout changes during 20-min clips |
| DuckDB replacing SQLite | 18K rows — SQLite handles in ms |
| SQLite WAL streaming | Pipeline is batch, no live event stream |
| Multi-layer caching | "Real-time, not cached" is scored requirement |
| API versioning | One consumer, not tested |
| Target 105-108/110 | Requires 90th+ percentile on all dimensions |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DETECTION PIPELINE                        │
│  CCTV Clips → YOLOv8m → ByteTrack → Zone Classification    │
│  → Staff Detection (3-tier heuristic) → Event Emission      │
│  → Schema Validation (15+ rules) → JSONL Output             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  INTELLIGENCE API                            │
│  FastAPI + SQLite (WAL mode) + Structured Logging           │
│  POST /events/ingest (idempotent, batch 500)                │
│  GET /stores/{id}/metrics, /funnel, /heatmap, /anomalies   │
│  GET /health (stale feed detection)                         │
│  Session Management + POS Correlation (5-min window)        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   WEB DASHBOARD                             │
│  Single HTML file served at GET /dashboard                  │
│  Chart.js + CSS grid, dark theme, polling every 5s          │
│  KPI cards, funnel chart, zone heatmap, anomaly feed        │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 0: Foundation (Hours 0-2) — NEVER CUT

### 0.1 Environment Setup
```bash
ls docs/
# Should see: CCTV footage zip, store_layout.json, pos_transactions.csv,
# sample_events.jsonl, assertions.py

mkdir -p pipeline/ app/ tests/ docs/
```

### 0.2 Analyze Provided Data
1. **Unzip CCTV footage** — identify all 5 stores × 3 cameras × 20min clips
2. **Parse `store_layout.json`** — extract zone definitions, camera coverage mappings, open hours per store
3. **Parse `pos_transactions.csv`** — understand schema, date range, store IDs, transaction volumes
4. **Parse `sample_events.jsonl`** — reverse-engineer the expected event schema precisely
5. **Run `assertions.py`** — understand the 10 test cases your API must pass

### 0.3 Throughput Benchmark (CRITICAL)
```bash
# Before building anything, measure detection speed:
python -c "
from ultralytics import YOLO
import time
model = YOLO('yolov8m.pt')
# Run on 1 minute of footage (900 frames at 15fps)
start = time.time()
# ... process frames ...
elapsed = time.time() - start
fps = 900 / elapsed
print(f'YOLOv8m: {fps:.1f} fps on this hardware')
if fps < 2:
    print('WARNING: Switch to YOLOv8n immediately')
"
```
- If <2 fps on 640p: drop to **YOLOv8n** and accept accuracy hit
- If 2-5 fps: process every 3rd frame (5 effective fps)
- If >5 fps: process every 2nd frame (7.5 effective fps)

### 0.4 store_layout.json Parsing
- Allocate 1-2 hours for reverse-engineering if format is unexpected
- Document the schema in DESIGN.md

---

## Phase 1: Detection Pipeline (Hours 2-18) — 30 Points

### Architecture: YOLOv8 + ByteTrack + Distance-based Re-ID

**Why YOLOv8:**
- Best speed/accuracy tradeoff for 1080p@15fps CCTV
- Pre-trained on COCO (person class = class 0)
- Easy to containerize (ultralytics package)
- Proven on millions of CCTV frames

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
    → Staff Detection (3-tier heuristic)
    → Event Emission (JSONL output)
    → Schema Validation (15+ rules)
```

**Key Implementation Details:**

#### Person Detection
- Use `yolov8m.pt` (medium model) — fallback to `yolov8n.pt` if too slow
- Confidence threshold: 0.35 (catch partial occlusions, don't suppress low-conf)
- Input: 1080p frames downscaled to 640 for inference, map back to original coords
- Frame skipping: process every 2nd frame (7.5 effective fps) or every 3rd (5 fps) based on benchmark

#### Tracking (ByteTrack)
- `track_thresh`: 0.35 (match detection threshold)
- `high_thresh`: 0.6 (confirmed track threshold)
- `match_thresh`: 0.8 (association threshold)
- `track_buffer`: 60 frames (4 seconds at 15fps — handle brief occlusions)
- Each track gets a persistent `track_id` within a clip

#### Entry/Exit Detection
- Define entry zone as a polygon from `store_layout.json` entry camera coverage
- **Direction logic:** Track centroid of each person's bounding box over time
  - Moving INTO the store → `ENTRY`
  - Moving OUT OF the store → `EXIT`
- Use velocity vector over 15 frames (1 second) to determine direction
- **Threshold:** Person's bottom-center must cross the entry line

#### Zone Classification
- Load zone polygons from `store_layout.json`
- For each frame, check if person's bottom-center point is inside any zone polygon
- Use `shapely.geometry.Point` for point-in-polygon tests
- Zone transitions emit `ZONE_ENTER` / `ZONE_EXIT` events
- `ZONE_DWELL` emitted every 30 seconds of continuous zone presence

#### Visitor ID Assignment (Re-ID)
- **Within a single clip:** Use ByteTrack's persistent `track_id` directly
- **Across cameras (same store):** Use entry/exit zone + time window matching
  - Match by spatial position in overlapping zones + time proximity
- **Re-entry detection:** If a visitor exits and then a new person enters within 5 minutes from the same direction → assign same visitor_id, emit REENTRY event
- **Visitor ID format:** `VIS_` + first 6 chars of UUID5(store_id + entry_time)

#### Staff Detection (3-Tier Heuristic)

| Tier | Rule | Threshold | Failure Mode |
|------|------|-----------|--------------|
| 1 — Duration | Track spans >85% of clip duration | ~17 min in 20-min clip | Customer loitering |
| 2 — Zone entropy | >0.5 zone changes per minute | Calibrate on 1 clip first | Fast-moving customer |
| 3 — Positional prior | Person in staff-only area | Boolean zone flag | Staff behind counter serving customer |

**Calibration plan:** Run Tier 2 on 1 clip, count zone changes per minute for known customers vs known staff, set threshold at mean(staff) - 0.5σ. If uncalibratable, drop Tier 2 and rely on Tiers 1+3.

#### Group Handling
- ByteTrack assigns separate `track_id`s per person
- Pipeline emits one ENTRY per track_id
- Each gets its own visitor_id

#### Confidence Calibration
- Pass through raw YOLOv8 confidence scores
- Flag detections with confidence < 0.3 as low-quality in metadata

### 1.2 Event Schema Implementation (`pipeline/emit.py`)

```python
event = {
    "event_id": str(uuid4()),
    "store_id": store_id,
    "camera_id": camera_id,
    "visitor_id": visitor_id,
    "event_type": event_type,
    "timestamp": iso8601_utc,
    "zone_id": zone_id,
    "dwell_ms": dwell_duration_ms,
    "is_staff": is_staff_bool,
    "confidence": yolo_confidence,
    "metadata": {
        "queue_depth": queue_depth,
        "sku_zone": zone_label,
        "session_seq": sequence_num
    }
}
```

**Event Type Emission Rules:**
| Event | Trigger |
|-------|---------|
| ENTRY | Person crosses entry threshold inbound |
| EXIT | Person crosses entry threshold outbound |
| ZONE_ENTER | Person enters named zone polygon |
| ZONE_EXIT | Person leaves named zone polygon |
| ZONE_DWELL | In zone continuously for 30+ sec |
| BILLING_QUEUE_JOIN | Enters billing zone while queue_depth > 0 |
| BILLING_QUEUE_ABANDON | Leaves billing zone before POS txn |
| REENTRY | Same visitor_id after prior EXIT |

### 1.3 Schema Validation (`pipeline/validate.py`)

Standalone validator checking 15+ rules on every emitted event:
- `event_id` is valid UUID v4 and globally unique
- `store_id` matches known stores from `store_layout.json`
- `camera_id` format matches `CAM_*_01` pattern
- `visitor_id` format matches `VIS_*` pattern
- `event_type` is one of the 8 allowed values
- `timestamp` is valid ISO-8601 UTC
- `zone_id` is null for ENTRY/EXIT, valid zone for others
- `dwell_ms` is integer, 0 for instantaneous events
- `is_staff` is boolean
- `confidence` is float 0-1
- `metadata` has correct structure for each event type

### 1.4 Pipeline Runner (`pipeline/run.sh`)

```bash
#!/bin/bash
CLIPS_DIR=${1:-./data/clips}
OUTPUT=${2:-./data/events.jsonl}

python pipeline/detect.py \
  --clips-dir "$CLIPS_DIR" \
  --store-layout ./data/store_layout.json \
  --output "$OUTPUT" \
  --model yolov8m \
  --conf-threshold 0.35

python pipeline/validate.py "$OUTPUT"
```

### 1.5 Edge Cases

| Edge Case | Solution |
|-----------|----------|
| **Group entry (2-4 people)** | ByteTrack assigns individual tracks; one ENTRY per track_id |
| **Staff movement** | 3-tier heuristic detection |
| **Re-entry** | Match exiting visitor_id by trajectory + time window (<5min gap) |
| **Partial occlusion** | YOLOv8 handles well; confidence threshold 0.35 |
| **Billing queue buildup** | Count people in billing zone polygon; track queue_depth |
| **Empty store periods** | No events emitted, API returns zero metrics |
| **Camera overlap** | Spatial matching in overlapping zones + time proximity |
| **POS correlation** | 5-minute window: visitor in billing zone within 5min of POS txn |

---

## Phase 2: Intelligence API (Hours 18-30) — 35 Points

### Architecture: FastAPI + SQLite (WAL mode)

### 2.1 API Structure (`app/`)

```
app/
├── main.py          # FastAPI app, middleware, CORS
├── models.py        # Pydantic schemas for events, responses
├── database.py      # SQLite connection, table creation, WAL mode
├── ingestion.py     # POST /events/ingest logic
├── metrics.py       # GET /stores/{id}/metrics
├── funnel.py        # GET /stores/{id}/funnel
├── heatmap.py       # GET /stores/{id}/heatmap
├── anomalies.py     # GET /stores/{id}/anomalies
├── health.py        # GET /health
├── session.py       # Session management, visitor dedup
└── dashboard.py     # GET /dashboard (serves HTML)
```

### 2.2 Database Schema

```sql
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    visitor_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    zone_id TEXT,
    dwell_ms INTEGER DEFAULT 0,
    is_staff BOOLEAN DEFAULT FALSE,
    confidence REAL DEFAULT 0.0,
    metadata_json TEXT,
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
- Partial success: `{"accepted": 498, "rejected": 2, "errors": [...]}`
- Store in SQLite

#### GET /stores/{id}/metrics
```python
{
    "store_id": "STORE_BLR_002",
    "date": "2026-03-03",
    "unique_visitors": 42,
    "conversion_rate": 0.357,
    "avg_dwell_per_zone": {"SKINCARE": 180000, "MAKEUP": 240000},
    "current_queue_depth": 3,
    "abandonment_rate": 0.15,
    "total_entries": 48,
    "total_exits": 45,
    "staff_excluded_count": 6
}
```

#### GET /stores/{id}/funnel
```python
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

#### GET /stores/{id}/heatmap
```python
{
    "store_id": "STORE_BLR_002",
    "zones": [
        {"zone_id": "SKINCARE", "visit_count": 35, "avg_dwell_ms": 180000, "score": 85},
        {"zone_id": "MAKEUP", "visit_count": 42, "avg_dwell_ms": 120000, "score": 100},
        {"zone_id": "BILLING", "visit_count": 22, "avg_dwell_ms": 60000, "score": 52}
    ],
    "data_confidence": "high"
}
```

#### GET /stores/{id}/anomalies
```python
{
    "store_id": "STORE_BLR_002",
    "anomalies": [
        {
            "type": "BILLING_QUEUE_SPIKE",
            "severity": "WARN",
            "description": "Queue depth 8 exceeds normal threshold of 4",
            "detected_at": "2026-03-03T14:35:00Z",
            "suggested_action": "Open additional billing counter"
        }
    ]
}
```

**Anomaly detection logic:**
- **BILLING_QUEUE_SPIKE:** queue_depth > 2× rolling average (or > 6 absolute)
- **CONVERSION_DROP:** current conversion < 50% of 7-day average
- **DEAD_ZONE:** zone with no ZONE_ENTER events in 30 minutes

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
- STALE_FEED warning if > 10 minutes since last event

### 2.4 Session Management (`app/session.py`)

```python
class SessionManager:
    def create_session(self, visitor_id, entry_event):
        # New session with entry timestamp
        
    def check_reentry(self, visitor_id, entry_event, time_window_minutes=5):
        # If visitor exited < time_window_minutes ago → REENTRY
        
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
    billing_events = [e for e in events 
                      if e.visitor_id == visitor_id 
                      and e.zone_id == "BILLING"
                      and e.event_type in ("ZONE_ENTER", "ZONE_DWELL")]
    
    store_pos = [t for t in pos_transactions if t.store_id == store_id]
    
    for txn in store_pos:
        txn_time = parse_timestamp(txn.timestamp)
        for bev in billing_events:
            bev_time = parse_timestamp(bev.timestamp)
            if 0 <= (txn_time - bev_time).total_seconds() <= 300:
                return True
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

### 3.5 assertions.py Debugging (1 hour allocated)

- Run `assertions.py` against the API
- Fix any failures immediately
- This is a hard gate requirement

### 3.6 README.md

```markdown
# Store Intelligence API — Apex Retail

## Quick Start (5 commands)
git clone <repo-url>
cd store-intelligence
docker compose up --build

# In another terminal, run detection pipeline:
docker compose run pipeline

# API is now available at http://localhost:8000
# Dashboard at http://localhost:8000/dashboard
# Docs at http://localhost:8000/docs

## Architecture
[Brief description with diagram]

## Running Detection Pipeline
[Step-by-step instructions]

## API Endpoints
[Table of endpoints]

## Design Decisions
See DESIGN.md and CHOICES.md
```

---

## Phase 4: AI Engineering Documentation (Hours 38-44) — 15 Points

### 4.1 DESIGN.md (~500-700 words)

```
# Architecture Overview
[Mermaid diagram showing data flow end-to-end]

# Detection Pipeline
[YOLOv8 → ByteTrack → Zone Classification → Staff Detection → Event Emission]

# Intelligence API
[FastAPI → SQLite → Real-time Metrics]

# Data Flow
[CCTV → Pipeline → Events → API → Dashboard]

# AI-Assisted Decisions (REQUIRED SECTION)
## 1. Detection Model Selection
AI suggested YOLOv8 over YOLOv9 for better ecosystem support.
I agreed — ultralytics package is production-ready with better docs.
[Include actual prompt excerpt]

## 2. Staff Detection Approach
AI suggested using a VLM for staff classification. I tried it and found
it works for sample frames but is too slow for batch processing.
I overrode with a 3-tier heuristic approach.
[Include actual prompt excerpt]

## 3. Zone Classification
AI suggested using VLM for zone classification. I found polygon-based
point-in-polygon is faster and more reliable for fixed camera setups.
I overrode — VLM adds latency with no accuracy gain.

## 4. Schema Validation
AI suggested adding a validation layer before API ingestion.
I agreed — catches bugs before they reach the scoring harness.

## 5. Re-ID Strategy
AI suggested OSNet for cross-camera matching. I found faces are blurred
across the dataset, making appearance-based Re-ID unreliable.
I overrode with distance-based trajectory matching.

# Failure Mode Analysis
[For each component, what breaks and how it degrades]

# What I Would Do Differently
[Self-awareness section]

# Trade-offs
[What you chose and what you gave up]
```

### 4.2 CHOICES.md (~500-700 words)

**5 decisions with structured format:**

```
## Decision: Detection Model

### Options Considered
- YOLOv8m (proven, good ecosystem)
- YOLOv9 (better small-person accuracy, worse docs)
- RT-DETR (transformer-based, no NMS, complex setup)

### AI's Recommendation
YOLOv8 — best ecosystem, proven for person detection

### My Assessment
Agreed. 48-hour window favors battle-tested tools.

### Final Choice
YOLOv8m — proven, well-documented, sufficient accuracy

### What I Gave Up
~3% AP gain from RT-DETR, ~5% small-person AP from YOLOv9

---

## Decision: Staff Detection Method

### Options Considered
- Duration heuristic (>30 min presence)
- Uniform color detection
- CLIP zero-shot classification
- 3-tier heuristic (duration + zone entropy + positional)

### AI's Recommendation
CLIP zero-shot — no training needed, works on any uniform

### My Assessment
CLIP is too slow on CPU (7.5 hours for full dataset).
Zone entropy is clever but uncalibrated.

### Final Choice
3-tier heuristic: duration (>85% clip) + zone entropy (>0.5/min) + positional prior

### What I Gave Up
CLIP's generalization to unseen uniforms, accuracy on edge cases

---

## Decision: Event Schema Design

### Options Considered
- Flat schema (as specified)
- Nested schema
- Event-sourced schema

### AI's Recommendation
Flat schema with metadata object

### My Assessment
Agreed. Metadata object allows extension without schema changes.

### Final Choice
Follow exact schema from problem statement, add metadata for flexibility

### What I Gave Up
Schema flexibility of nested/event-sourced approaches

---

## Decision: API Architecture

### Options Considered
- FastAPI + SQLite
- FastAPI + PostgreSQL
- Flask + Redis

### AI's Recommendation
FastAPI + PostgreSQL for production-readiness

### My Assessment
SQLite is sufficient for 18K rows. Docker compose simplicity matters.

### Final Choice
FastAPI + SQLite (with WAL mode for concurrent reads)

### What I Gave Up
PostgreSQL's concurrent write performance, JSON query support

---

## Decision: Validation Strategy

### Options Considered
- Schema validation at pipeline output
- Schema validation at API ingestion
- Both (defense in depth)

### AI's Recommendation
Both — validate early and late

### My Assessment
Pipeline validation catches bugs before they reach the API.
API validation is the scoring gate.

### Final Choice
Both: pipeline/validate.py (15+ rules) + Pydantic models at API layer

### What I Gave Up
Slightly more code, but negligible overhead
```

---

## Phase 5: Web Dashboard (Hours 44-47) — COMMITTED, NEVER CUT

### 5.1 Architecture

Single HTML file served at `GET /dashboard`. Zero build tooling, zero bundler.

```
GET /dashboard → FastAPI route → returns dashboard.html
                                     ↓
                        Browser polls 5 APIs every 5s:
                          - /stores/{id}/metrics
                          - /stores/{id}/funnel  
                          - /stores/{id}/heatmap
                          - /stores/{id}/anomalies
                          - /health (for store list + status)
```

### 5.2 Components

| Component | Data Source | Visual |
|-----------|------------|--------|
| **KPI Cards** (4) | `/metrics` | Large numbers with color coding (green/yellow/red) |
| **Funnel Chart** | `/funnel` | Chart.js horizontal bars — Entry → Zone Visit → Billing → Purchase |
| **Zone Heatmap** | `/heatmap` | Table with color-scored rows (CSS gradient 0-100) |
| **Anomaly Feed** | `/anomalies` | Card list with severity badges (CRITICAL=pulse, WARN=yellow, INFO=blue) |

**Store selector** dropdown (populated from `/health`). **Auto-refresh** every 5 seconds with timestamp. **Dark theme** via CSS custom properties. **Mobile-responsive** via CSS grid.

### 5.3 Implementation

**File:** `app/dashboard.html` (single file, ~600 lines total)

**CSS (~200 lines):**
- CSS Grid layout (mobile: 1 column, tablet: 2, desktop: 4 for KPIs)
- Dark theme via CSS custom properties (`--bg: #1a1a2e`, `--card: #16213e`)
- No framework — clean CSS

**JavaScript (~250 lines):**
- `pollData()`: `Promise.all()` to all 5 endpoints every 5s
- `updateKPI(data)`, `updateFunnel(data)`, `updateHeatmap(data)`, `updateAnomalies(data)`
- Chart.js instance for funnel (destroy + recreate on update)
- Store selected store ID in global var
- `setInterval(pollData, 5000)` after initial fetch

**FastAPI route:**
```python
from fastapi.responses import HTMLResponse

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)
```

### 5.4 Implementation Time: 3 hours

| Task | Time |
|------|------|
| HTML structure + CSS grid layout | 45 min |
| KPI cards with color logic | 30 min |
| Funnel Chart.js integration | 30 min |
| Heatmap table with conditional coloring | 20 min |
| Anomaly feed | 20 min |
| Store selector + polling logic | 25 min |
| Responsive tweaks + polish | 30 min |

---

## Timeline (48 Hours)

| Phase | Hours | What | Kill Priority |
|-------|-------|------|---------------|
| **0: Foundation** | **0-2** | Data analysis, store_layout.json parsing, throughput benchmark | Never |
| **1a: Detection Core** | **2-10** | YOLOv8m + ByteTrack + zone classification + event emission | Never |
| **1b: Detection Refinement** | **10-16** | Staff detection (3 tiers), re-entry, group handling | Tier 3 → Tier 2 |
| **1c: Detection Polish** | **16-18** | Schema validator, validate against sample_events.jsonl | Never |
| **2: Intelligence API** | **18-28** | FastAPI + SQLite + all endpoints + session management | Anomalies sophistication |
| **3: Production** | **28-34** | Docker, logging, tests, assertions.py debugging | Test coverage below 70% |
| **4: Documentation** | **34-40** | DESIGN.md + CHOICES.md (6 hours) | Never |
| **5: Dashboard** | **40-43** | Web UI (single HTML, Chart.js, 3 hours) | Never |
| **6: Buffer** | **43-48** | Final polish, acceptance gate check, fix window leverage | — |

### Kill Order (if running behind)

1. Anomaly detection sophistication (keep basic queue spike + conversion drop)
2. Heatmap endpoint sophistication (keep basic response)
3. Test coverage below 70% (keep critical 10 tests)
4. Staff detection Tier 3 (keep Tiers 1+2)
5. **Dashboard: NEVER CUT** — committed at 3 hours

### Never Sacrifice

- Schema compliance (Part A: 10 pts)
- Idempotent ingest (Part B: explicitly tested)
- Containerization + acceptance gate (C: 5 pts + gate to scoring)
- DESIGN.md and CHOICES.md (D: 15 pts, zero code risk, highest ROI)
- Web dashboard (E: +10 pts, committed)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| YOLOv8 too slow on CPU | Medium | High | Benchmark in Phase 0. Drop to YOLOv8n if <2fps. Process every 3rd frame. |
| ByteTrack loses tracks during occlusion | Medium | Medium | Lower track_thresh to 0.3. Increase track_buffer to 90 frames. |
| Staff detection misclassifies customers | High | Medium | 3-tier heuristic with tunable thresholds. Document expected error rate. |
| store_layout.json format unexpected | Medium | Medium | Allocate 1-2 hours in Phase 0 for reverse-engineering. |
| Docker build fails on clean machine | Low | Critical | Test `docker compose up` on fresh container before submission. |
| assertions.py tests fail | Medium | Critical | Allocate 1 hour debugging in Phase 3. Fix immediately. |
| Time runs out | Medium | High | Follow kill order. Parts A+B = 65 pts without anything else. |
| 12-hour fix window needed | Low | Medium | If gate fails at hour 46, use fix window. Don't panic-submit. |

---

## Acceptance Checklist (Submission Day)

```bash
# 1. Build and start
docker compose up --build

# 2. Verify health
curl http://localhost:8000/health
# → {"status": "healthy", "stores": {...}}

# 3. Ingest events (batch of 500)
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  -d @data/events_batch.json
# → {"accepted": 498, "rejected": 2, "errors": [...]}

# 4. Check metrics
curl http://localhost:8000/stores/STORE_BLR_002/metrics
# → {"unique_visitors": 42, "conversion_rate": 0.357, ...}

# 5. Check funnel
curl http://localhost:8000/stores/STORE_BLR_002/funnel
# → {"stages": [...], "overall_conversion": 0.357}

# 6. Check heatmap
curl http://localhost:8000/stores/STORE_BLR_002/heatmap
# → {"zones": [...], "data_confidence": "high"}

# 7. Check anomalies
curl http://localhost:8000/stores/STORE_BLR_002/anomalies
# → {"anomalies": [...]}

# 8. Dashboard is live
# Open http://localhost:8000/dashboard in browser
# → Charts updating every 5 seconds

# 9. Run assertions
python assertions.py
# → All 10 assertions pass

# 10. Run tests
pytest tests/ --cov=app --cov-report=term-missing
# → >70% coverage

# 11. Docs exist
wc -w docs/DESIGN.md docs/CHOICES.md
# → >250 words each
```

---

## What Success Looks Like

At hour 48, before submission:

1. `docker compose up --build` works on clean machine
2. Detection pipeline produces schema-compliant events
3. All 10 `assertions.py` tests pass
4. All API endpoints return correct data
5. Dashboard live at `localhost:8000/dashboard` with real-time charts
6. >70% test coverage
7. DESIGN.md and CHOICES.md are substantial (>250 words each)
8. 5-hour buffer for final debugging

**This is achievable.** Every component is well-understood. No experimental models. No unproven integrations. Solid engineering with clear documentation and thorough validation.
