#!/usr/bin/env python3
"""
Generate 200+ sample events matching the required schema for STORE_BLR_002.

Event types: ENTRY, EXIT, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL,
             BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON, REENTRY

Produces events for ~15 visitors over a 20-minute window:
2026-04-10T11:00:00Z to 2026-04-10T11:20:00Z
"""

import json
import uuid
import random
from datetime import datetime, timedelta

random.seed(42)

OUTPUT = "data/sample_events.jsonl"

STORE_ID = "STORE_BLR_002"
CAMERAS = ["CAM_ENTRY_01", "CAM_MAIN_01", "CAM_BILLING_01", "CAM_MAIN_02", "CAM_BILLING_02"]

ZONE_SEQUENCE = ["ENTRY", "BROWSING", "SKINCARE", "MAKEUP", "BILLING"]

def random_visitor_id():
    return "VIS_" + uuid.uuid4().hex[:6]

def make_event(event_type, camera_id, visitor_id, timestamp, zone_id=None,
               dwell_ms=0, is_staff=False, confidence=0.9,
               queue_depth=None, sku_zone=None, session_seq=1):
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(timestamp, datetime) else timestamp,
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": round(confidence, 2),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": sku_zone,
            "session_seq": session_seq
        }
    }

BASE = datetime(2026, 4, 10, 11, 0, 0)

def random_time(offset_minutes=0, max_offset=20):
    return BASE + timedelta(minutes=offset_minutes, seconds=random.randint(0, 59))

def generate_visitor_journey(visitor_id, start_offset, is_staff=False):
    """Generate a realistic journey for one visitor."""
    events = []
    seq = 1
    t = random_time(start_offset)

    # ENTRY
    cam = "CAM_ENTRY_01"
    events.append(make_event("ENTRY", cam, visitor_id, t,
                             is_staff=is_staff,
                             confidence=random.uniform(0.7, 0.95),
                             session_seq=seq))
    seq += 1

    # Move through zones
    zones = ZONE_SEQUENCE[1:4]  # BROWSING, SKINCARE, MAKEUP
    if is_staff:
        zones = ["BROWSING", "STAFF_AREA", "BILLING"]

    for zi, zone in enumerate(zones):
        # Some delay between zone entries
        dwell = random.randint(30, 300)
        t += timedelta(seconds=dwell)

        # Pick camera based on zone
        cam_map = {
            "BROWSING": random.choice(["CAM_MAIN_01", "CAM_MAIN_02"]),
            "SKINCARE": random.choice(["CAM_MAIN_01", "CAM_MAIN_02"]),
            "MAKEUP": random.choice(["CAM_MAIN_01", "CAM_MAIN_02"]),
            "STAFF_AREA": random.choice(["CAM_BILLING_01", "CAM_BILLING_02"]),
            "BILLING": random.choice(["CAM_BILLING_01", "CAM_BILLING_02"]),
        }

        cam = cam_map.get(zone, "CAM_MAIN_01")
        conf = random.uniform(0.4, 0.95)

        # ZONE_ENTER
        events.append(make_event("ZONE_ENTER", cam, visitor_id, t,
                                 zone_id=zone, is_staff=is_staff,
                                 confidence=conf,
                                 session_seq=seq))
        seq += 1

        # ZONE_DWELL (emit every 30s; 1-3 dwell events per zone)
        dwell_evts = random.randint(1, 3)
        for de in range(dwell_evts):
            t += timedelta(seconds=30)
            sku_map = {
                "SKINCARE": random.choice(["MOISTURISER", "SERUM", "SUNSCREEN", "TONER", "CLEANSER"]),
                "MAKEUP": random.choice(["FOUNDATION", "LIPSTICK", "EYELINER", "CONCEALER"]),
                "BROWSING": random.choice(["DISPLAY", "PROMO"]),
                "BILLING": None,
                "STAFF_AREA": None,
            }
            events.append(make_event("ZONE_DWELL", cam, visitor_id, t,
                                     zone_id=zone, is_staff=is_staff,
                                     dwell_ms=random.randint(30000, 300000),
                                     confidence=conf,
                                     sku_zone=sku_map.get(zone),
                                     session_seq=seq))
            seq += 1

        # ZONE_EXIT
        t += timedelta(seconds=random.randint(5, 30))
        events.append(make_event("ZONE_EXIT", cam, visitor_id, t,
                                 zone_id=zone, is_staff=is_staff,
                                 confidence=conf,
                                 session_seq=seq))
        seq += 1

    # BILLING zone - if not staff
    if not is_staff:
        t += timedelta(seconds=random.randint(10, 60))
        cam = random.choice(["CAM_BILLING_01", "CAM_BILLING_02"])
        conf = random.uniform(0.5, 0.95)
        events.append(make_event("ZONE_ENTER", cam, visitor_id, t,
                                 zone_id="BILLING", confidence=conf,
                                 session_seq=seq))
        seq += 1

        # Maybe queue join
        if random.random() < 0.7:
            t += timedelta(seconds=random.randint(5, 15))
            qd = random.randint(1, 5)
            events.append(make_event("BILLING_QUEUE_JOIN", cam, visitor_id, t,
                                     zone_id="BILLING", confidence=conf,
                                     queue_depth=qd,
                                     session_seq=seq))
            seq += 1

            # Dwell in billing
            dwell_b = random.randint(1, 2)
            for _ in range(dwell_b):
                t += timedelta(seconds=30)
                events.append(make_event("ZONE_DWELL", cam, visitor_id, t,
                                         zone_id="BILLING",
                                         dwell_ms=random.randint(30000, 180000),
                                         confidence=conf,
                                         session_seq=seq))
                seq += 1

            # Maybe abandon queue
            if random.random() < 0.15:
                t += timedelta(seconds=random.randint(5, 30))
                events.append(make_event("BILLING_QUEUE_ABANDON", cam, visitor_id, t,
                                         zone_id="BILLING", confidence=conf,
                                         session_seq=seq))
                seq += 1

        t += timedelta(seconds=random.randint(5, 20))
        events.append(make_event("ZONE_EXIT", cam, visitor_id, t,
                                 zone_id="BILLING", confidence=conf,
                                 session_seq=seq))
        seq += 1

    # EXIT
    t += timedelta(seconds=random.randint(10, 60))
    cam = "CAM_ENTRY_01"
    events.append(make_event("EXIT", cam, visitor_id, t,
                             is_staff=is_staff,
                             confidence=random.uniform(0.7, 0.95),
                             session_seq=seq))
    seq += 1

    return events

def main():
    events = []

    # Generate ~12 customer journeys
    visitor_ids = []
    for i in range(12):
        vid = random_visitor_id()
        visitor_ids.append(vid)
        offset = random.randint(0, 18)
        evts = generate_visitor_journey(vid, offset, is_staff=False)
        events.extend(evts)

    # Generate ~3 staff journeys
    for i in range(3):
        vid = "STAFF_" + uuid.uuid4().hex[:6]
        offset = random.randint(0, 18)
        evts = generate_visitor_journey(vid, offset, is_staff=True)
        events.extend(evts)

    # Generate ~3 REENTRY events (same visitor_id AFTER their EXIT)
    # First, collect each customer's EXIT timestamp
    exit_times = {}
    for evt in events:
        if evt["event_type"] == "EXIT" and not evt["visitor_id"].startswith("STAFF_"):
            vid = evt["visitor_id"]
            exit_times[vid] = evt["timestamp"]

    for vid in random.sample(visitor_ids, 3):
        if vid not in exit_times:
            continue
        # Parse EXIT time and add a gap (1-5 minutes)
        exit_dt = datetime.strptime(exit_times[vid], "%Y-%m-%dT%H:%M:%SZ")
        reentry_dt = exit_dt + timedelta(minutes=random.randint(1, 5), seconds=random.randint(0, 59))
        ct = random.random()
        if ct < 0.33:
            events.append(make_event("REENTRY", "CAM_ENTRY_01", vid, reentry_dt,
                                     confidence=random.uniform(0.5, 0.85),
                                     session_seq=random.randint(10, 20)))
        elif ct < 0.66:
            events.append(make_event("REENTRY", "CAM_ENTRY_01", vid, reentry_dt,
                                     confidence=random.uniform(0.5, 0.85),
                                     session_seq=random.randint(10, 20)))
            reentry_dt += timedelta(seconds=random.randint(30, 120))
            events.append(make_event("ZONE_ENTER", "CAM_MAIN_01", vid, reentry_dt,
                                     zone_id="BROWSING",
                                     confidence=random.uniform(0.4, 0.8),
                                     session_seq=random.randint(11, 21)))
        else:
            events.append(make_event("REENTRY", "CAM_ENTRY_01", vid, reentry_dt,
                                     confidence=random.uniform(0.5, 0.85),
                                     session_seq=random.randint(10, 20)))
            reentry_dt += timedelta(seconds=random.randint(60, 180))
            events.append(make_event("ZONE_ENTER", "CAM_BILLING_01", vid, reentry_dt,
                                     zone_id="BILLING",
                                     confidence=random.uniform(0.5, 0.8),
                                     session_seq=random.randint(11, 21)))

    # Add some low-confidence events
    for _ in range(5):
        vid = random_visitor_id()
        t = random_time(random.randint(0, 19))
        events.append(make_event("ENTRY", "CAM_ENTRY_01", vid, t,
                                 confidence=random.uniform(0.3, 0.5),
                                 session_seq=1))
        t += timedelta(seconds=random.randint(10, 60))
        events.append(make_event("EXIT", "CAM_ENTRY_01", vid, t,
                                 confidence=random.uniform(0.3, 0.5),
                                 session_seq=2))

    # Shuffle events so they're not perfectly ordered
    random.shuffle(events)

    # Sort by timestamp for realism
    events.sort(key=lambda e: e["timestamp"])

    with open(OUTPUT, "w") as f:
        for evt in events:
            f.write(json.dumps(evt) + "\n")

    print(f"Generated {len(events)} events to {OUTPUT}")

if __name__ == "__main__":
    main()
