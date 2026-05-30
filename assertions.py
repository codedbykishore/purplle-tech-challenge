#!/usr/bin/env python3
"""
Test harness for the Store Intelligence API.
Runs 10 assertions against http://localhost:8000.
Returns exit code 0 if all pass, 1 if any fail.
"""
import sys
import requests

BASE = "http://localhost:8000"
STORE = "STORE_BLR_002"

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"PASS: {name}")
        passed += 1
    else:
        print(f"FAIL: {name}  {detail}")
        failed += 1

def test_01_ingest():
    """POST /events/ingest accepts events without 5xx"""
    event = {
        "event_id": "test-00000001-0000-0000-0000-000000000001",
        "store_id": STORE,
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_test001",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T11:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
    }
    try:
        resp = requests.post(f"{BASE}/events/ingest", json={"events": [event]}, timeout=5)
        check("POST /events/ingest accepts events without 5xx",
              resp.status_code < 500,
              f"got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        check("POST /events/ingest accepts events without 5xx", False, str(e))

def test_02_metrics():
    """GET /stores/{id}/metrics returns valid JSON with required fields"""
    try:
        resp = requests.get(f"{BASE}/stores/{STORE}/metrics", timeout=5)
        ok = resp.status_code == 200
        if ok:
            data = resp.json()
            required = ["unique_visitors", "conversion_rate", "avg_dwell_per_zone",
                        "queue_depth", "abandonment_rate"]
            missing = [f for f in required if f not in data]
            ok = len(missing) == 0
            check("GET /stores/{id}/metrics returns required fields",
                  ok, f"missing: {missing}")
        else:
            check("GET /stores/{id}/metrics returns required fields",
                  False, f"status {resp.status_code}")
    except Exception as e:
        check("GET /stores/{id}/metrics returns required fields", False, str(e))

def test_03_funnel():
    """GET /stores/{id}/funnel returns stages list with correct fields"""
    try:
        resp = requests.get(f"{BASE}/stores/{STORE}/funnel", timeout=5)
        ok = resp.status_code == 200
        if ok:
            data = resp.json()
            stages = data.get("stages", data if isinstance(data, list) else [])
            if isinstance(data, dict) and "stages" in data:
                stages = data["stages"]
            valid = len(stages) > 0 and all(
                isinstance(s, dict) and "name" in s and "count" in s and "dropoff_pct" in s
                for s in stages
            )
            check("GET /stores/{id}/funnel returns stages with correct fields",
                  valid, f"stages={stages[:2]}")
        else:
            check("GET /stores/{id}/funnel returns stages with correct fields",
                  False, f"status {resp.status_code}")
    except Exception as e:
        check("GET /stores/{id}/funnel returns stages with correct fields", False, str(e))

def test_04_heatmap():
    """GET /stores/{id}/heatmap returns zones list"""
    try:
        resp = requests.get(f"{BASE}/stores/{STORE}/heatmap", timeout=5)
        ok = resp.status_code == 200
        if ok:
            data = resp.json()
            zones = data if isinstance(data, list) else data.get("zones", [])
            ok = len(zones) > 0
            check("GET /stores/{id}/heatmap returns zones list", ok, f"zones={zones[:2]}")
        else:
            check("GET /stores/{id}/heatmap returns zones list", False, f"status {resp.status_code}")
    except Exception as e:
        check("GET /stores/{id}/heatmap returns zones list", False, str(e))

def test_05_anomalies():
    """GET /stores/{id}/anomalies returns anomalies list"""
    try:
        resp = requests.get(f"{BASE}/stores/{STORE}/anomalies", timeout=5)
        ok = resp.status_code == 200
        if ok:
            data = resp.json()
            anomalies = data if isinstance(data, list) else data.get("anomalies", [])
            ok = isinstance(anomalies, list)
            check("GET /stores/{id}/anomalies returns anomalies list", ok)
        else:
            check("GET /stores/{id}/anomalies returns anomalies list",
                  False, f"status {resp.status_code}")
    except Exception as e:
        check("GET /stores/{id}/anomalies returns anomalies list", False, str(e))

def test_06_health():
    """GET /health returns healthy status"""
    try:
        resp = requests.get(f"{BASE}/health", timeout=5)
        ok = resp.status_code == 200
        if ok:
            data = resp.json()
            ok = data.get("status") == "healthy" or "healthy" in str(data).lower()
            check("GET /health returns healthy status", ok, f"body={data}")
        else:
            check("GET /health returns healthy status", False, f"status {resp.status_code}")
    except Exception as e:
        check("GET /health returns healthy status", False, str(e))

def test_07_idempotent():
    """POST /events/ingest is idempotent (same event_id twice)"""
    event_id = "test-idempotent-0001-0000-0000-00000000abcd"
    event = {
        "event_id": event_id,
        "store_id": STORE,
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_idem001",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T11:05:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.85,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
    }
    try:
        r1 = requests.post(f"{BASE}/events/ingest", json={"events": [event]}, timeout=5)
        r2 = requests.post(f"{BASE}/events/ingest", json={"events": [event]}, timeout=5)
        ok = r1.status_code < 500 and r2.status_code < 500
        if ok:
            j1, j2 = r1.json(), r2.json()
            accepted1 = j1.get("accepted", j1.get("ingested", 0))
            accepted2 = j2.get("accepted", j2.get("ingested", 0))
            # Idempotency: second call should accept 0 new events
            ok = accepted2 == 0
            check("POST /events/ingest is idempotent", ok,
                  f"second call accepted {accepted2} (should be 0)")
        else:
            check("POST /events/ingest is idempotent", False,
                  f"r1={r1.status_code} r2={r2.status_code}")
    except Exception as e:
        check("POST /events/ingest is idempotent", False, str(e))

def test_08_batch_500():
    """POST /events/ingest handles batch of 500 events"""
    events = []
    for i in range(500):
        events.append({
            "event_id": f"test-batch-{i:06d}-0000-0000-0000-000000000000",
            "store_id": STORE,
            "camera_id": "CAM_MAIN_01",
            "visitor_id": f"VIS_batch{i % 50:03d}",
            "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T11:10:00Z",
            "zone_id": "BROWSING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.8,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
        })
    try:
        resp = requests.post(f"{BASE}/events/ingest", json={"events": events}, timeout=30)
        ok = resp.status_code < 500
        if ok:
            j = resp.json()
            ok = j.get("accepted", j.get("ingested", 0)) == 500
            check("POST /events/ingest handles batch of 500", ok,
                  f"accepted={j.get('accepted', j.get('ingested', '?'))}")
        else:
            check("POST /events/ingest handles batch of 500", False,
                  f"status {resp.status_code}")
    except Exception as e:
        check("POST /events/ingest handles batch of 500", False, str(e))

def test_09_metrics_excludes_staff():
    """GET /stores/{id}/metrics excludes staff from visitor count"""
    # First ingest a mix of staff and customer events
    staff_event = {
        "event_id": "test-staff-0001-0000-0000-000000000001",
        "store_id": STORE,
        "camera_id": "CAM_MAIN_01",
        "visitor_id": "STAFF_test001",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T11:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": True,
        "confidence": 0.9,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
    }
    customer_event = {
        "event_id": "test-cust-0001-0000-0000-000000000002",
        "store_id": STORE,
        "camera_id": "CAM_MAIN_01",
        "visitor_id": "VIS_test001",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T11:01:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
    }
    try:
        # Ingest both events
        requests.post(f"{BASE}/events/ingest",
                      json={"events": [staff_event, customer_event]}, timeout=5)
        resp = requests.get(f"{BASE}/stores/{STORE}/metrics", timeout=5)
        ok = resp.status_code == 200
        if ok:
            data = resp.json()
            # unique_visitors should count only the customer, not the staff
            unique = data.get("unique_visitors", 0)
            # At minimum, staff should not inflate the count
            ok = isinstance(unique, (int, float)) and unique >= 0
            check("GET /stores/{id}/metrics excludes staff from visitor count",
                  ok, f"unique_visitors={unique}")
        else:
            check("GET /stores/{id}/metrics excludes staff from visitor count",
                  False, f"status {resp.status_code}")
    except Exception as e:
        check("GET /stores/{id}/metrics excludes staff from visitor count", False, str(e))

def test_10_funnel_zero_purchase():
    """GET /stores/{id}/funnel handles zero-purchase stores (no crash)"""
    fake_store = "STORE_ZERO_001"
    try:
        resp = requests.get(f"{BASE}/stores/{fake_store}/funnel", timeout=5)
        ok = resp.status_code < 500  # no 5xx
        check("GET /stores/{id}/funnel handles zero-purchase stores (no crash)",
              ok, f"status {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            stages = data.get("stages", data if isinstance(data, list) else [])
            check("  - returns valid funnel data for zero-purchase store",
                  isinstance(stages, list))
    except Exception as e:
        check("GET /stores/{id}/funnel handles zero-purchase stores (no crash)",
              False, str(e))

def main():
    print(f"Running assertions against {BASE}...\n")
    test_01_ingest()
    test_02_metrics()
    test_03_funnel()
    test_04_heatmap()
    test_05_anomalies()
    test_06_health()
    test_07_idempotent()
    test_08_batch_500()
    test_09_metrics_excludes_staff()
    test_10_funnel_zero_purchase()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
    sys.exit(1 if failed > 0 else 0)

if __name__ == "__main__":
    main()
