# Design Choices — Store Intelligence

## Decision: Detection Model

### Options Considered
- YOLOv8m (proven, good ecosystem, 320x320 input)
- YOLOv9 (better small-person accuracy, worse documentation)
- RT-DETR (transformer-based, no NMS, complex setup)

### AI's Recommendation
YOLOv8 — best ecosystem, proven for person detection, production-ready

### My Assessment
Agreed. The 48-hour window favors battle-tested tools. YOLOv8m offers the best balance of accuracy, speed, and deployment maturity. The ultralytics package provides pre-trained weights, ONNX export, and comprehensive API.

### Final Choice
YOLOv8m — proven, well-documented, sufficient accuracy for retail person detection

### What I Gave Up
~3% AP gain from RT-DETR, ~5% small-person AP from YOLOv9

---

## Decision: Staff Detection Method

### Options Considered
- Duration heuristic (>30 min presence in store)
- Uniform color detection (HSV color space analysis)
- CLIP zero-shot classification (text-image matching)
- 3-tier heuristic (duration + zone entropy + positional prior)

### AI's Recommendation
CLIP zero-shot — no training needed, works on any uniform type

### My Assessment
CLIP is too slow on CPU (7.5 hours for the full dataset). Zone entropy is clever but uncalibrated without ground truth. The 3-tier heuristic combines three lightweight signals that are fast to compute and easy to tune.

### Final Choice
3-tier heuristic: duration (>85% clip presence) + zone entropy (>0.5 zones/min) + positional prior (BILLING/ENTRY zones)

### What I Gave Up
CLIP's generalization to unseen uniforms, accuracy on edge cases (e.g., staff in customer zones)

---

## Decision: Event Schema Design

### Options Considered
- Flat schema (as specified in problem statement)
- Nested schema (hierarchical event structure)
- Event-sourced schema (immutable event log with projections)

### AI's Recommendation
Flat schema with metadata object for extension

### My Assessment
Agreed. The metadata object allows extension without schema changes. The flat structure matches the scoring harness expectations and simplifies validation. Event-sourcing adds complexity without clear benefit for a single-store demo.

### Final Choice
Flat schema with metadata object — follows problem statement, allows flexible extensions

### What I Gave Up
Schema flexibility of nested approaches, auditability of event-sourced patterns

---

## Decision: API Architecture

### Options Considered
- FastAPI + SQLite (lightweight, single-file database)
- FastAPI + PostgreSQL (production-grade, concurrent writes)
- Flask + Redis (simple API, fast caching)

### AI's Recommendation
FastAPI + PostgreSQL for production-readiness and concurrent access

### My Assessment
SQLite is sufficient for 18K rows. Docker Compose simplicity matters — PostgreSQL adds a second service and configuration overhead. WAL mode handles concurrent reads well. The API is read-heavy (analytics queries) with batch writes (event ingestion).

### Final Choice
FastAPI + SQLite with WAL mode — lightweight, single-container deployment, sufficient for demo

### What I Gave Up
PostgreSQL's concurrent write performance, JSONB query support, full-text search

---

## Decision: Validation Strategy

### Options Considered
- Schema validation at pipeline output only
- Schema validation at API ingestion only
- Both (defense in depth)

### AI's Recommendation
Both — validate early and late for maximum error coverage

### My Assessment
Pipeline validation catches bugs in the detection code before they reach the API. API validation protects against malformed external requests. The 15-rule validator in `pipeline/validate.py` runs on every emitted event, while Pydantic models validate at the API boundary.

### Final Choice
Both layers — pipeline validator (15 rules) + API Pydantic models, defense in depth

### What I Gave Up
~5ms latency per event from double validation, slightly more code to maintain
