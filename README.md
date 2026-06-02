# Store Intelligence API — Apex Retail

A complete store intelligence system that transforms raw CCTV footage into actionable retail analytics: person detection, zone tracking, conversion funnels, and real-time anomaly detection.

## Quick Start

```bash
# 1. Clone and enter the repository
git clone <repo-url> && cd store-intelligence

# 2. Install dependencies
pip install -r requirements.txt

# 3. Initialize database and load sample data
python -c "from app.database import init_database, seed_pos_data; init_database(); seed_pos_data()"

# 4. Start the API server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 5. Run the detection pipeline (in another terminal)
python pipeline/detect.py
```

The API is available at `http://localhost:8000` and the dashboard at `http://localhost:8000/dashboard`.

## Docker

```bash
# Build and run both services
docker compose up --build

# Or run the detection pipeline separately
docker compose run pipeline
```

## Architecture

```
CCTV Footage → YOLOv8 Detection → Zone Classification → Event Emission → SQLite → FastAPI → Dashboard
```

The system has four layers:
1. **Detection**: YOLOv8 + ByteTrack for person detection and tracking
2. **Storage**: SQLite WAL mode with events and purchases tables
3. **API**: FastAPI with 6 analytics endpoints
4. **Dashboard**: Single HTML file with Chart.js visualizations

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events/ingest` | POST | Ingest batch of events (up to 500, idempotent) |
| `/health` | GET | Service health with per-store status |
| `/stores/{id}/metrics` | GET | Real-time store metrics |
| `/stores/{id}/funnel` | GET | Conversion funnel analysis |
| `/stores/{id}/heatmap` | GET | Zone heatmap data |
| `/stores/{id}/anomalies` | GET | Anomaly detection |
| `/dashboard` | GET | Web dashboard (HTML) |

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=app --cov=pipeline --cov-report=term-missing
```

## Documentation

- [DESIGN.md](docs/DESIGN.md) — Architecture overview, data flow, AI-assisted decisions
- [CHOICES.md](docs/CHOICES.md) — 5 key design decisions with trade-off analysis
- [Plan](docs/plan-v3-final.md) — Complete project plan and timeline

## Project Structure

```
├── app/
│   ├── main.py              # FastAPI application
│   ├── models.py            # Pydantic v2 models
│   ├── database.py          # SQLite WAL, schema, POS seeding
│   ├── session.py           # Visitor session management
│   ├── ingestion.py         # Event ingestion logic
│   └── dashboard.html       # Web dashboard
├── pipeline/
│   ├── detect.py            # YOLOv8 + ByteTrack detection
│   ├── emit.py              # Event emission helpers
│   ├── validate.py          # 15-rule schema validator
│   └── run.sh               # Pipeline runner script
├── tests/                   # 104 tests, ~80% coverage
├── data/
│   ├── store_layout.json    # Store zones and cameras
│   ├── pos_transactions.csv # POS transaction data
│   └── sample_events.jsonl  # Sample detection events
├── docs/
│   ├── DESIGN.md            # Architecture design
│   ├── CHOICES.md           # Design decisions
│   └── plan-v3-final.md     # Project plan
├── Dockerfile               # API container
├── Dockerfile.pipeline      # Pipeline container
├── docker-compose.yml       # Multi-service orchestration
└── assertions.py            # 10-test scoring harness
```
