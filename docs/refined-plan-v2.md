# Refined Plan v2 — Post-Critic

## Acknowledgment of Rejected Proposals

The Creator's v1.5 ambition added 16 features. The CRITIC rejected all of them. Justifiably.

Every rejected proposal shared a common pattern: **added complexity without scoring impact**, either because the dataset doesn't support it, the scoring harness can't test it, or the engineering cost exceeds the marginal gain.

### What Was Dropped (and why):

| Proposal | Why It's Gone |
|----------|---------------|
| RT-DETR replacing YOLOv8 | YOLOv8m gives ~52% mAP for person class. RT-DETR's ~3% gain is ~0.3 absolute points. Installation risk dwarfs benefit. |
| BoT-SORT + OSNet Re-ID | Faces are blurred per §3.2. OSNet degrades to clothing/body shape — same as distance-based but 10x model size. |
| CLIP-based staff detection | 54K classification calls at ~500ms each on CPU = 7.5 hours. Heuristic is faster, more robust, more interpretable. |
| Multi-camera homography | No calibration data. Homography error exceeds zone-overlap matching. Worse than the simpler approach. |
| SKU-level POS integration | No customer ID in POS. Can't map SKUs to visitors. Not tested. |
| Inventory alerting | No inventory data. "High dwell + no purchase" ≠ causation. |
| Slack/webhook notifications | Scoring harness runs in isolated Docker. Webhooks fail silently. Untestable. |
| Prophet forecasting | 20-minute clips. Prophet needs months of data. Comically mismatched. |
| k-means journey clustering | 30-50 visitors per clip. Arbitrary boundaries. Zero scoring impact. |
| Staff optimization engine | Requires causal model + A/B test. Can't validate. |
| Layout A/B testing | No layout changes during 20-min clips. No control group. |
| DuckDB replacing SQLite | 18K rows. SQLite handles in ms. DuckDB adds 6-10MB to Docker. |
| SQLite WAL streaming | Pipeline is batch. No live event stream. |
| Multi-layer caching | "Real-time, not cached" is a scored requirement. Query faster than cache lookup at this volume. |
| API versioning | One consumer. Not tested. Zero scoring impact. |
| Target 105-108/110 | Requires 90th+ percentile on all dimensions. Unrealistic in 48 hours. |

**Total proposals dropped: 16.** The refined plan below is the original v1 stripped of all unnecessary additions, then surgically strengthened in areas the critic implicitly endorsed.

---

## Refined Target: 94-98/110

| Part | Max | Target | Rationale |
|------|-----|--------|-----------|
| A: Detection Pipeline | 30 | 27 | Strong YOLOv8m baseline + schema validator; some accuracy loss expected |
| B: Intelligence API | 35 | 32 | Well-defined endpoints, solid session logic, good anomaly detection |
| C: Production Readiness | 20 | 19 | Comprehensive tests + robust error handling |
| D: AI Engineering | 15 | 14 | Heavy doc investment — this is the highest leverage per hour |
| E: Live Dashboard | +10 | +9 | Web dashboard (not just terminal) |
| **Total** | **110** | **94-98** | **Achievable with high confidence in 48 hours** |

No single dimension exceeds 90% of max. The aggregate is strong because every part works, not because any one part is perfect.

---

## The 3 Highest-Impact, Lowest-Risk Improvements

These are the only additions beyond the original v1. Each survives the critic's filter because each is:
- **Testable** within the scoring harness
- **Low-code-risk** (minimal new dependencies)
- **Directly tied to scored criteria**

### Improvement 1: Schema Validation Layer (Part A: +2-3 pts, Part D: +1 pt)

**What:** A standalone `pipeline/validate.py` that validates every emitted event against the full required schema *before* it reaches the API. Runs assertions on:
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

**Why it's low-risk:** Pure data validation. No model inference. No new dependencies. Entire file is ~150 lines of Python with `jsonschema` or custom validators.

**Scoring impact:** 
- Schema compliance (Part A: 10 pts) — this validator directly proves schema correctness
- Demonstrates engineering thoroughness (Part D: thinking systematically about validation)
- Catches bugs before they reach the API

**Implementation:**
```python
# pipeline/validate.py
VALID_EVENT_TYPES = {"ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", 
                     "ZONE_DWELL", "BILLING_QUEUE_JOIN", 
                     "BILLING_QUEUE_ABANDON", "REENTRY"}
VALID_STORE_IDS = {...}  # loaded from store_layout.json

def validate_event(event: dict) -> list[str]:
    """Returns list of validation errors. Empty list = valid."""
    errors = []
    # UUID format check
    # event_type in VALID_EVENT_TYPES
    # zone_id null check for ENTRY/EXIT
    # timestamp ISO-8601 regex
    # dwell_ms type check
    # ... 15+ validation rules
    return errors

def validate_events(events: list[dict]) -> tuple[int, int, list[dict]]:
    """Returns (accepted_count, rejected_count, errors_per_event)."""
```

**Integrated into pipeline:**
```bash
python pipeline/detect.py ... && python pipeline/validate.py data/events.jsonl
```

---

### Improvement 2: Staff Detection Refinement (Part A: +2-3 pts, Part D: +1 pt)

**What:** Replace the hand-wavy "uniform color + duration" with a concrete, documented 3-tier heuristic. Each tier is a function with clear inputs, outputs, and documented failure modes.

**The 3-Tier Staff Detector:**

1. **Duration Tier (primary):** Anyone with continuous presence > 30 minutes in a 20-minute clip window is staff. This catches staff who appear before the clip starts and remain. Implementation: check if track spans > 85% of clip duration.

2. **Zone Revisitation Tier:** Calculate zone entropy — staff visit many zones repeatedly (restocking, cleaning). Customers have more linear paths. Implementation: count distinct zone visits per minute of track lifetime. Staff threshold: > 0.5 zone changes per minute.

3.**Positional Prior Tier:** Staff are often found behind billing counters, in back-of-store areas not typically visited by customers. Implementation: define "staff-only zones" from store_layout.json (if present) or by detecting people who remain in the billing area for extended periods without queuing.

**Documentation strategy:** Each tier gets its own section in CHOICES.md with:
- What I tried first
- What didn't work
- What I settled on and why
- Known failure modes (e.g., loitering customer flagged as staff)

**Why it's low-risk:** Pure heuristic logic. No new model. No inference pipeline changes. ~80 lines of Python.

**Scoring impact:** 
- Staff exclusion (Part A: subset of 10 pts)
- Shows reasoned decision-making (Part D)
- The documented evolution from "simple duration" to "3-tier heuristic" is exactly what reviewers want to see

---

### Improvement 3: Documentation Depth Investment (Part D: +3-4 pts)

**What:** Upgrade DESIGN.md and CHOICES.md from "good" to "exceptional." Part D is 15 points and requires zero code risk. This is the single highest-leverage activity in the entire plan.

**Specific upgrades:**

**DESIGN.md upgrades:**
- Add a system architecture diagram (ASCII or Mermaid) showing data flow end-to-end
- The "AI-Assisted Decisions" section becomes the centerpiece, not an afterthought
- Include actual prompt excerpts from the conversation with the AI
- For each AI-assisted decision, include: "AI suggested X. I agreed because... / I overrode because..."
- Add a "What I Would Do Differently" section showing self-awareness
- Include a "Failure Mode Analysis" — for each component, what breaks and how it degrades

**CHOICES.md upgrades:**
- Expand from 3 decisions to 5 (the problem statement says 3 minimum, more is better)
- Add a decision on staff detection methodology (tied to Improvement 2 above)
- Add a decision on validation strategy (tied to Improvement 1 above)
- For each decision, use a structured format:
  ```
  ## Decision: [Title]
  
  ### Options Considered
  - Option A: ... (pros/cons)
  - Option B: ... (pros/cons)
  - Option C: ... (pros/cons)
  
  ### AI's Recommendation
  [What the AI suggested and the reasoning it gave]
  
  ### My Assessment
  [Whether I agreed or disagreed, and why]
  
  ### Final Choice
  [What I went with and the specific rationale]
  
  ### What I Gave Up
  [Honest trade-off acknowledgment]
  ```

**Why this is high-impact, low-risk:**
- Zero code changes. Zero bugs. Zero regression.
- 15 points = 15% of total score, entirely in your control
- The evaluation says reviewers spend 2 minutes reading these docs — make every sentence count
- Follow-up questions are generated from CHOICES.md — better docs = easier video answers

**Time allocation:** 6 hours (up from 4 in original v1). This is the best 6 hours you can spend.

---

## What Else Stays from v1 (Strengthened, Not Replaced)

The following core architecture is unchanged but refined:

| Component | v1 Approach | v2 Refinement |
|-----------|-------------|---------------|
| Detection | YOLOv8m + ByteTrack | Same. Add frame-skipping config (process every 2nd frame at 15fps → 7.5fps effective). Add explicit error handling for corrupt frames. |
| Re-ID | Distance-based (trajectory) | Same. Add IoU-based matching across overlapping camera zones. Document failure cases (lookalike strangers). |
| Zone classification | Shapely point-in-polygon | Same. Add caching of zone polygons. Document coordinate system assumptions. |
| Entry/Exit detection | Velocity vector over 15 frames | Same. Add configurable direction threshold. Handle edge case of person standing at threshold. |
| Staff detection | Duration + uniform color | Upgraded to 3-tier heuristic (see Improvement 2 above). |
| Event emission | JSONL per clip | Same. Add schema validation step (see Improvement 1 above). |
| API framework | FastAPI + SQLite | Same. Add request-id middleware. Better error messages. |
| Session management | ENTRY→EXIT with REENTRY | Same. Better documentation of edge cases. |
| POS correlation | 5-min billing window | Same. Document the assumption explicitly. |
| Anomaly detection | Queue spike, conversion drop | Same. Add rate-limiting to anomaly emission (don't emit 50 queue spikes in 2 minutes). |
| Docker | Two Dockerfiles + compose | Same. Add healthcheck. Add .dockerignore. Pin Python version. |
| Logging | structlog, trace_id per request | Same. Add request body size logging for ingest. Add slow query logging (>100ms). |
| Tests | pytest, >70% coverage | Same. Add specific edge case tests from the 7 known challenges. |
| Dashboard | Terminal + web | Same. Prioritize web dashboard from the start (higher score). |

---

## Realistic Timeline (48 Hours)

This is tighter than v1 because I'm being honest about time for debugging.

| Phase | Hours | What | Dependencies |
|-------|-------|------|-------------|
| **0: Foundation** | **0-2** | Dataset inspection, store_layout parse, schema reverse-engineering, assertions.py analysis | Dataset ZIP |
| **1a: Detection Core** | **2-10** | YOLOv8m + ByteTrack pipeline, basic detection + tracking on 1 clip | Phase 0 |
| **1b: Detection Logic** | **10-18** | Zone classification, entry/exit direction, event emission, staff detection (3-tier) | Phase 1a |
| **1c: Detection Polish** | **18-22** | Schema validator, run on all clips, fix bugs, validate against sample_events.jsonl | Phase 1b |
| **2a: API Core** | **22-28** | FastAPI skeleton, SQLite schema, POST /events/ingest, GET /health | Phase 1c |
| **2b: API Logic** | **28-34** | GET /metrics, /funnel, /heatmap, /anomalies, session management, POS correlation | Phase 2a |
| **3a: Production** | **34-38** | Docker setup, structured logging, error handling, graceful degradation | Phase 2b |
| **3b: Tests** | **38-42** | Test suite: pipeline tests, API tests, edge case tests, >70% coverage | Phase 3a |
| **4: Docs** | **42-47** | DESIGN.md, CHOICES.md, README.md, prompt blocks in test files | Phase 3b |
| **5: Dashboard** | **47-52** | Web dashboard (Chart.js polls API every 5s) | Phase 2b |
| **Buffer** | **52-54** | End-to-end validation, docker compose up test on clean env, final fixes | All |

**Total: 54 hours of work in 48-hour window.** The 6-hour overage is real — I will cut from:
- Phase 1b first (simplify staff detection if heuristic is problematic)
- Phase 5 next (terminal dashboard is always the fallback)
- Phase 3b (reduce test count but keep critical path tests)

### Priority Kill Order

If running out of time, sacrifice in this order:

1. Dashboard bells and whistles (keep basic web UI)
2. Non-critical test cases (keep the 10 critical ones from v1 §3.4)
3. Heatmap endpoint (simplest API endpoint, least scoring weight at 5/35)
4. Anomaly detection sophistication (keep basic queue spike + conversion drop)
5. Staff detection tier 3 (positional prior) — duration + zone entropy still work

**Never sacrifice:**
- Schema compliance (Part A: 10 pts)
- Idempotent ingest (Part B: explicitly tested)
- Containerisation + acceptance gate (C: 5 pts + gate to scoring)
- DESIGN.md and CHOICES.md (D: 15 pts, zero code risk, highest ROI)

---

## Risk Register (Updated for v2)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| YOLOv8 too slow on CPU | Medium | High | Process every 3rd frame (5fps). Use YOLOv8n (nano) as fallback. Downscale to 480p. |
| ByteTrack loses tracks during occlusion | Medium | Medium | Lower track_thresh to 0.3. Increase track_buffer to 90 frames (6s). |
| Staff detection misclassifies customers | High | Medium | Tiered approach with tunable thresholds. Document expected error rate in CHOICES.md. |
| POS correlation is inaccurate | Medium | Medium | 5-min window is the problem statement's own guidance. Document limitation. |
| Docker build fails on clean machine | Low | Critical (gate) | Test `docker compose up` on a fresh `python:3.11-slim` container before submission. |
| Time runs out | Medium | High | Follow the kill order above. Parts A+B = 65 pts without anything else. |
| Follow-up questions reveal shallow understanding | Low | Medium | Good docs + actual code knowledge = easy answers. Each question maps to a documented decision. |

---

## Scoring Walkthrough (94-98/110)

Let me trace exactly where the points come from:

### Part A: Detection Pipeline (Target: 27/30)

| Criterion | Max | Target | Justification |
|-----------|-----|--------|---------------|
| Entry/Exit count accuracy | 10 | 8 | YOLOv8m is strong but not perfect at 15fps. Expect ±15% error. |
| Staff exclusion, re-entry, group | 10 | 9 | 3-tier staff detector handles most cases. ByteTrack handles groups naturally. |
| Schema compliance | 10 | 10 | Schema validator catches every deviation. 100% compliance is achievable. |

### Part B: Intelligence API (Target: 32/35)

| Criterion | Max | Target | Justification |
|-----------|-----|--------|---------------|
| Endpoint correctness | 20 | 18 | All endpoints return correct, consistent data. Minor edge cases may slip. |
| Funnel + session dedup | 10 | 9 | Session manager prevents double-counting. REENTRY handling is solid. |
| Anomaly detection | 5 | 5 | Queue spike + conversion drop + dead zone are well-defined. |

### Part C: Production Readiness (Target: 19/20)

| Criterion | Max | Target | Justification |
|-----------|-----|--------|---------------|
| Containerisation + README | 5 | 5 | Docker compose works. README covers setup in 5 commands. |
| Logging + health | 5 | 5 | structlog + trace_id + request logging. Health endpoint with per-store status. |
| Tests + edge cases | 10 | 9 | >70% coverage. All 10 critical edge cases tested. Some non-critical gaps. |

### Part D: AI Engineering (Target: 14/15)

| Criterion | Max | Target | Justification |
|-----------|-----|--------|---------------|
| CHOICES.md depth | 5 | 5 | 5 decisions with structured format, AI interaction documented for each. |
| DESIGN.md architecture | 5 | 5 | Clear system view, AI-Assisted Decisions section, failure mode analysis. |
| Reasoning depth | 5 | 4 | Some trade-offs could be deeper. But 4/5 is strong. |

### Part E: Dashboard (Target: 9/10)

| Criterion | Max | Target | Justification |
|-----------|-----|--------|---------------|
| Live dashboard | 10 | 9 | Web UI with Chart.js. Real-time polling. May not be perfectly polished. |

**Total: 27 + 32 + 19 + 14 + 9 = 101 → conservative estimate 94-98 after reviewer variance.**

---

## What Success Looks Like

At hour 48, before submission:

```bash
# 1. Clean machine test
git clone <repo>
cd store-intelligence
docker compose up --build -d

# 2. API responds
curl http://localhost:8000/health
# → {"status":"healthy","stores":{...}}

# 3. Detection pipeline produces events
docker compose run pipeline
# → Events written to data/events.jsonl

# 4. Schema validation passes
python pipeline/validate.py data/events.jsonl
# → 0 errors, 0 warnings

# 5. Events ingested
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  -d @data/events_batch.json
# → {"accepted": 500, "rejected": 0, "errors": []}

# 6. Metrics return real data
curl http://localhost:8000/stores/STORE_BLR_002/metrics
# → {"unique_visitors": 42, "conversion_rate": 0.357, ...}

# 7. Dashboard is live at localhost:8000/dashboard
# → Charts updating every 5 seconds

# 8. Tests pass with >70% coverage
pytest tests/ --cov=app --cov=pipeline --cov-report=term
# → 42 passed, coverage 73%

# 9. Docs exist and are non-trivial
wc -w docs/DESIGN.md docs/CHOICES.md
# → 850 + 920 = 1770 words (>250 each)
```

This is achievable. Every component is well-understood. No experimental models. No unproven integrations. Just solid engineering with clear documentation and thorough validation.
