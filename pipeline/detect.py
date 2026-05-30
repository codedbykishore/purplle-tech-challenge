#!/usr/bin/env python3
"""Detection pipeline: CCTV clips → structured events.

Processes video clips through YOLOv8 person detection, IOU-based tracking,
zone classification via Shapely, and structured event emission.

Processes video clips through YOLOv8 person detection, IOU-based tracking,
zone classification via Shapely, and structured event emission.

Usage:
    python pipeline/detect.py \
        --clips-dir ./data/clips \
        --store-layout ./data/store_layout.json \
        --output ./data/events.jsonl \
        --model yolov8m \
        --conf-threshold 0.35
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except ImportError:
    print("WARNING: ultralytics not installed. Run: pip install ultralytics")
    YOLO = None

try:
    from shapely.geometry import Point, Polygon
except ImportError:
    print("WARNING: shapely not installed. Run: pip install shapely")
    Point = Polygon = None

from pipeline.emit import (
    emit_entry, emit_exit, emit_zone_enter, emit_zone_exit,
    emit_zone_dwell, emit_billing_queue_join, emit_billing_queue_abandon,
    emit_reentry, events_to_jsonl,
)


# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

DEFAULT_MODEL = "yolov8m"
DEFAULT_CONF = 0.35
FRAME_SKIP = 2  # Process every 2nd frame (7.5 effective fps from 15fps)
ENTRY_THRESHOLD_FRAMES = 15  # ~1 second velocity window at effective fps
DWELL_EMIT_INTERVAL_MS = 30_000  # Emit ZONE_DWELL every 30 seconds while in zone
PERSON_CLASS_ID = 0  # COCO person class
IOU_THRESHOLD = 0.3  # IOU threshold for track matching
MAX_LOST_FRAMES = 60  # Remove track after ~4 seconds without detection


# ──────────────────────────────────────────────────────────────
# Store Layout Loading
# ──────────────────────────────────────────────────────────────

def load_store_layout(layout_path: str) -> dict[str, Any]:
    """Load and parse store_layout.json."""
    with open(layout_path) as f:
        return json.load(f)


def get_zones(store_data: dict[str, Any]) -> dict[str, "Polygon"]:
    """Extract zone polygons from store layout. Returns {zone_id: Polygon}."""
    zones: dict[str, Polygon] = {}
    if Point is None or Polygon is None:
        print("WARNING: shapely not available, zone classification disabled")
        return zones

    store = store_data.get("stores", [{}])[0]
    for zone in store.get("zones", []):
        coords = zone.get("polygon", [])
        if coords and len(coords) >= 3:
            zones[zone["zone_id"]] = Polygon(coords)
    return zones


def get_cameras(store_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract camera configs from the first store entry."""
    store = store_data.get("stores", [{}])[0]
    return store.get("cameras", [])


def get_camera_zones(store_data: dict[str, Any]) -> dict[str, list[str]]:
    """Extract camera_id → [zone_ids] mapping from the first store entry."""
    store = store_data.get("stores", [{}])[0]
    return store.get("camera_coverage", {})


# ──────────────────────────────────────────────────────────────
# Zone Classification
# ──────────────────────────────────────────────────────────────

def classify_point(
    x: float, y: float, zones: dict[str, Polygon]
) -> str | None:
    """Classify a 2D point into a zone. Returns zone_id or None."""
    if Point is None:
        return None
    point = Point(x, y)
    for zone_id, polygon in zones.items():
        if polygon.contains(point) or polygon.touches(point):
            return zone_id
    return None


# ──────────────────────────────────────────────────────────────
# Coordinate Mapping (pixel → floor-plan)
# ──────────────────────────────────────────────────────────────

def map_pixel_to_floor(px: float, py: float, frame_w: int, frame_h: int,
                       camera_id: str) -> tuple[float, float]:
    """Map pixel coordinates to approximate floor-plan coordinates.

    Since we don't have calibration data, we use a simplified mapping:
    - Each camera has a known coverage area in the store layout
    - We map the pixel frame into that coverage area

    Store is 15m × 10m. Floor-plan coords: x=[0,15], y=[0,10].
    """
    # Normalize pixel to 0-1
    nx = px / frame_w if frame_w > 0 else 0.5
    ny = py / frame_h if frame_h > 0 else 0.5

    # Map based on camera type
    if "ENTRY" in camera_id:
        # Entry camera covers x=[0,3], y=[0,2]
        fx = nx * 3.0
        fy = ny * 2.0
    elif "BILLING" in camera_id:
        # Billing cameras cover x=[12,15], y=[6,10]
        fx = 12.0 + nx * 3.0
        fy = 6.0 + ny * 4.0
    else:
        # Main cameras cover x=[3,12], y=[0,8]
        fx = 3.0 + nx * 9.0
        fy = ny * 8.0

    return fx, fy


# ──────────────────────────────────────────────────────────────
# IOU-Based Object Tracker (SORT-like, no Kalman filter)
# ──────────────────────────────────────────────────────────────

class SimpleIOUTracker:
    """Simple IOU-based multi-object tracker.

    Assigns persistent track IDs across frames by matching bounding boxes
    with maximum IOU above a threshold. New tracks are created for unmatched
    detections; stale tracks are removed after MAX_LOST_FRAMES.
    """

    def __init__(self, iou_threshold: float = IOU_THRESHOLD,
                 max_lost: int = MAX_LOST_FRAMES):
        self._next_id = 1
        self._tracks: dict[int, dict[str, Any]] = {}
        self._iou_threshold = iou_threshold
        self._max_lost = max_lost

    @staticmethod
    def _compute_iou(bbox_a: tuple[float, float, float, float],
                     bbox_b: tuple[float, float, float, float]) -> float:
        """Compute intersection-over-union of two axis-aligned bounding boxes."""
        x1 = max(bbox_a[0], bbox_b[0])
        y1 = max(bbox_a[1], bbox_b[1])
        x2 = min(bbox_a[2], bbox_b[2])
        y2 = min(bbox_a[3], bbox_b[3])

        if x2 < x1 or y2 < y1:
            return 0.0

        inter = (x2 - x1) * (y2 - y1)
        area_a = (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1])
        area_b = (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1])
        union = area_a + area_b - inter

        return inter / union if union > 0 else 0.0

    def _cleanup(self) -> None:
        """Remove tracks that have been lost for too long."""
        stale = [tid for tid, t in self._tracks.items()
                 if t["lost"] > self._max_lost]
        for tid in stale:
            del self._tracks[tid]

    def update(
        self, detections: list[tuple[float, float, float, float]]
    ) -> dict[int, int]:
        """Match detections to existing tracks.

        Args:
            detections: List of (x1, y1, x2, y2) pixel coordinates.

        Returns:
            Dict mapping detection index (into the input list) → track_id.
        """
        num_dets = len(detections)
        result: dict[int, int] = {}
        assigned_tids: set[int] = set()
        assigned_dets: set[int] = set()

        if num_dets == 0:
            for tid in list(self._tracks.keys()):
                self._tracks[tid]["lost"] += 1
            self._cleanup()
            return result

        track_ids = list(self._tracks.keys())

        # Build IOU matrix between existing tracks and new detections
        if track_ids:
            iou_matrix = np.zeros((len(track_ids), num_dets), dtype=np.float64)
            for i, tid in enumerate(track_ids):
                for j in range(num_dets):
                    iou_matrix[i, j] = self._compute_iou(
                        self._tracks[tid]["bbox"], detections[j]
                    )

            # Greedy matching: assign highest-IOU pairs first
            matches: list[tuple[float, int, int, int]] = []
            for i, tid in enumerate(track_ids):
                for j in range(num_dets):
                    matches.append((iou_matrix[i, j], i, j, tid))
            matches.sort(key=lambda x: x[0], reverse=True)

            for iou_val, i, j, tid in matches:
                if iou_val < self._iou_threshold:
                    break
                if tid in assigned_tids or j in assigned_dets:
                    continue
                assigned_tids.add(tid)
                assigned_dets.add(j)
                # Update existing track with matched detection
                self._tracks[tid]["bbox"] = detections[j]
                self._tracks[tid]["lost"] = 0
                result[j] = tid

            # Mark unmatched tracks as lost
            for tid in track_ids:
                if tid not in assigned_tids:
                    self._tracks[tid]["lost"] += 1

        # Create new tracks for unmatched detections
        for j in range(num_dets):
            if j not in assigned_dets:
                new_id = self._next_id
                self._next_id += 1
                self._tracks[new_id] = {"bbox": detections[j], "lost": 0}
                result[j] = new_id

        self._cleanup()
        return result

    def get_active_tracks(self) -> list[int]:
        """Return list of currently active (not lost) track IDs."""
        return [tid for tid, t in self._tracks.items() if t["lost"] == 0]


# ──────────────────────────────────────────────────────────────
# Velocity & Zone History Tracker
# ──────────────────────────────────────────────────────────────

class Tracker:
    """Tracks per-ID history for velocity-based direction and zone transitions."""

    def __init__(self):
        # track_id → list of (timestamp, bottom_center_y)
        self._histories: dict[int, list[tuple[float, float]]] = {}
        self._zone_history: dict[int, str | None] = {}
        self._visitor_ids: dict[int, str] = {}
        self._first_event_time: dict[str, datetime] = {}
        self._last_event_time: dict[str, datetime] = {}
        self._session_seq: dict[str, int] = {}
        self._video_start_time: datetime | None = None

    def update(self, track_id: int, bottom_center_y: float,
               timestamp: float) -> None:
        """Record a new observation for a track."""
        if track_id not in self._histories:
            self._histories[track_id] = []
        self._histories[track_id].append((timestamp, bottom_center_y))
        # Keep last 30 frames (~2 seconds at effective fps)
        self._histories[track_id] = self._histories[track_id][-30:]

    def get_direction(self, track_id: int) -> str | None:
        """Determine direction based on velocity over recent frames.

        Returns:
            'ENTRY' — moving into store (y decreasing, toward top of frame)
            'EXIT'  — moving out of store (y increasing, toward bottom)
            None    — insufficient data or stationary
        """
        history = self._histories.get(track_id, [])
        if len(history) < ENTRY_THRESHOLD_FRAMES:
            return None

        recent = history[-ENTRY_THRESHOLD_FRAMES:]
        y_values = [h[1] for h in recent]
        dy = y_values[-1] - y_values[0]
        dt = recent[-1][0] - recent[0][0]
        if dt <= 0:
            return None
        velocity = dy / dt

        if velocity < -0.5:
            return "ENTRY"
        elif velocity > 0.5:
            return "EXIT"
        return None

    def set_zone(self, track_id: int, zone_id: str | None) -> None:
        """Record the current zone for a track."""
        self._zone_history[track_id] = zone_id

    def get_zone(self, track_id: int) -> str | None:
        """Get the last known zone for a track."""
        return self._zone_history.get(track_id)

    def get_visitor_id(self, track_id: int, store_id: str) -> str:
        """Get or create a persistent visitor_id for a track."""
        if track_id not in self._visitor_ids:
            self._visitor_ids[track_id] = "VIS_" + uuid.uuid4().hex[:6]
        return self._visitor_ids[track_id]

    def record_event_time(self, visitor_id: str, dt: datetime) -> None:
        """Track the first and last event time for a visitor."""
        if visitor_id not in self._first_event_time:
            self._first_event_time[visitor_id] = dt
        self._last_event_time[visitor_id] = dt

    def get_first_event_time(self, visitor_id: str) -> datetime | None:
        return self._first_event_time.get(visitor_id)

    def get_last_event_time(self, visitor_id: str) -> datetime | None:
        return self._last_event_time.get(visitor_id)

    def get_session_seq(self, visitor_id: str) -> int:
        """Get and increment the session sequence counter for a visitor."""
        seq = self._session_seq.get(visitor_id, 0) + 1
        self._session_seq[visitor_id] = seq
        return seq

    def get_all_visitors(self) -> list[str]:
        """Return set of all tracked visitor IDs."""
        return list(set(self._visitor_ids.values()))

    def check_reentry(self, visitor_id: str, time_window_minutes: int = 5) -> bool:
        """Check if a visitor's last EXIT was recent enough for re-entry."""
        last_exit = self._last_event_time.get(visitor_id)
        if last_exit is None or self._video_start_time is None:
            return False
        # Use video-relative time: compare last exit to current video time
        # (not wall-clock time)
        video_now = self._video_start_time + timedelta(seconds=0)  # placeholder
        gap = (last_exit - self._video_start_time).total_seconds() / 60
        return gap <= time_window_minutes

    def set_video_start_time(self, dt: datetime) -> None:
        """Record the video's start timestamp for relative time calculations."""
        self._video_start_time = dt


# ──────────────────────────────────────────────────────────────
# Staff Detection (3-Tier Heuristic)
# ──────────────────────────────────────────────────────────────

class StaffDetector:
    """Simple staff detection based on duration heuristic.

    Tier 1: If a track spans > threshold_pct of the clip duration, mark as staff.
    """

    def __init__(self, clip_duration_frames: int,
                 threshold_pct: float = 0.85):
        self._track_durations: dict[int, int] = {}
        self._clip_duration = clip_duration_frames
        self._threshold = threshold_pct

    def update(self, track_id: int) -> None:
        """Increment the observed frame count for a track."""
        self._track_durations[track_id] = \
            self._track_durations.get(track_id, 0) + 1

    def is_staff(self, track_id: int) -> bool:
        """Return True if track spans > threshold_pct of the clip."""
        duration = self._track_durations.get(track_id, 0)
        return duration > (self._clip_duration * self._threshold)


# ──────────────────────────────────────────────────────────────
# Queue Detection Helpers
# ──────────────────────────────────────────────────────────────

def count_in_billing_zone(
    current_positions: dict[int, tuple[float, float]],
    billing_polygon: Polygon | None,
    zones: dict[str, Polygon],
) -> int:
    """Count people currently located in the billing zone."""
    if billing_polygon is None:
        return 0
    count = 0
    for track_id, (x, y) in current_positions.items():
        if classify_point(x, y, {"BILLING": billing_polygon}) == "BILLING":
            count += 1
    return count


# ──────────────────────────────────────────────────────────────
# Main Processing
# ──────────────────────────────────────────────────────────────

def process_clip(
    clip_path: str,
    store_id: str,
    camera_id: str,
    store_data: dict[str, Any],
    model: "YOLO",
    conf_threshold: float = DEFAULT_CONF,
) -> list[dict[str, Any]]:
    """Process a single video clip and return a list of structured events."""
    events: list[dict[str, Any]] = []
    zones = get_zones(store_data)
    billing_polygon = zones.get("BILLING")

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open {clip_path}")
        return events

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_interval = 1.0 / fps

    iou_tracker = SimpleIOUTracker()
    tracker = Tracker()
    staff_detector = StaffDetector(total_frames)

    # Set video start time for re-entry detection
    tracker.set_video_start_time(datetime.fromtimestamp(0, tz=timezone.utc))

    # Track zone entry times per (track_id, zone_id) for dwell calculation
    # Structure: {track_id: {zone_id: entry_timestamp}}
    zone_entry_times: dict[int, dict[str, float]] = {}

    # Current positions for queue depth tracking
    current_positions: dict[int, tuple[float, float]] = {}

    frame_count = 0

    print(f"Processing {clip_path} ({total_frames} frames, {fps:.1f} fps)")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        if frame_count % FRAME_SKIP != 0:
            continue

        timestamp = frame_count * frame_interval

        # Resize frame for faster inference (640px width)
        h, w = frame.shape[:2]
        scale = 640 / w
        resized = cv2.resize(frame, (640, int(h * scale)))

        # Run YOLOv8 detection
        results = model(resized, conf=conf_threshold, verbose=False)

        # Collect person detections for this frame
        raw_detections: list[tuple[float, float, float, float, float]] = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for box in boxes:
                cls = int(box.cls[0])
                if cls != PERSON_CLASS_ID:
                    continue

                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                # Map coordinates back to original frame dimensions
                x1_orig, y1_orig = x1 / scale, y1 / scale
                x2_orig, y2_orig = x2 / scale, y2 / scale

                raw_detections.append((x1_orig, y1_orig, x2_orig, y2_orig, conf))

        # Run IOU tracking to assign persistent IDs
        if raw_detections:
            bboxes = [d[:4] for d in raw_detections]
            tracked = iou_tracker.update(bboxes)

            for det_idx, track_id in tracked.items():
                x1_orig, y1_orig, x2_orig, y2_orig, conf = raw_detections[det_idx]

                # Bottom-center point for zone classification
                center_x = (x1_orig + x2_orig) / 2.0
                bottom_y = y2_orig

                # Update velocity / position history
                tracker.update(track_id, bottom_y, timestamp)
                staff_detector.update(track_id)

                # Map pixel coords to floor-plan coords before zone classification
                fx, fy = map_pixel_to_floor(center_x, bottom_y, w, h, camera_id)
                zone_id = classify_point(fx, fy, zones)
                prev_zone = tracker.get_zone(track_id)
                tracker.set_zone(track_id, zone_id)

                # Determine visitor ID and staff status
                visitor_id = tracker.get_visitor_id(track_id, store_id)
                is_staff = staff_detector.is_staff(track_id)

                # Tier 3: staff if in staff-only zone
                if zone_id == "STAFF_AREA":
                    is_staff = True

                # Track position for queue depth
                current_positions[track_id] = (center_x, bottom_y)

                # Build shared timestamp
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                seq = tracker.get_session_seq(visitor_id)
                tracker.record_event_time(visitor_id, dt)

                # ── Zone transition events ──────────────────────────
                if zone_id != prev_zone:
                    # Emit ZONE_EXIT for the previous zone
                    if prev_zone is not None:
                        events.append(emit_zone_exit(
                            store_id, camera_id, visitor_id, dt,
                            zone_id=prev_zone, is_staff=is_staff,
                            confidence=conf, session_seq=seq,
                        ))

                        # Clear dwell tracking for the exited zone
                        if track_id in zone_entry_times \
                                and prev_zone in zone_entry_times[track_id]:
                            del zone_entry_times[track_id][prev_zone]

                    # Emit ZONE_ENTER for the new zone
                    if zone_id is not None:
                        events.append(emit_zone_enter(
                            store_id, camera_id, visitor_id, dt,
                            zone_id=zone_id, is_staff=is_staff,
                            confidence=conf, session_seq=seq,
                        ))

                        # Initialize dwell tracking
                        if track_id not in zone_entry_times:
                            zone_entry_times[track_id] = {}
                        zone_entry_times[track_id][zone_id] = timestamp

                        # Check for billing queue join
                        if zone_id == "BILLING" and billing_polygon is not None:
                            queue_depth = count_in_billing_zone(
                                current_positions, billing_polygon, zones
                            )
                            if queue_depth > 1:  # At least one other person
                                events.append(emit_billing_queue_join(
                                    store_id, camera_id, visitor_id, dt,
                                    queue_depth=queue_depth,
                                    confidence=conf, session_seq=seq,
                                ))

                # ── Zone dwell event (every DWELL_EMIT_INTERVAL_MS) ─
                if zone_id is not None and track_id in zone_entry_times \
                        and zone_id in zone_entry_times[track_id]:
                    entry_ts = zone_entry_times[track_id][zone_id]
                    dwell_seconds = timestamp - entry_ts
                    if dwell_seconds >= DWELL_EMIT_INTERVAL_MS / 1000.0:
                        events.append(emit_zone_dwell(
                            store_id, camera_id, visitor_id, dt,
                            zone_id=zone_id,
                            dwell_ms=int(dwell_seconds * 1000),
                            is_staff=is_staff,
                            confidence=conf, session_seq=seq,
                        ))
                        # Reset dwell timer for this track+zone
                        zone_entry_times[track_id][zone_id] = timestamp

        else:
            # No detections in this frame — still need to update tracker
            # so it can increment lost counters and clean up stale tracks
            iou_tracker.update([])

    cap.release()

    # ── Emit ENTRY / EXIT events using velocity-based direction ─
    for track_id, visitor_id in tracker._visitor_ids.items():
        direction = tracker.get_direction(track_id)
        is_staff = staff_detector.is_staff(track_id)

        # Tier 3: check if track spent significant time in staff-only zone
        if tracker.get_zone(track_id) == "STAFF_AREA":
            is_staff = True

        if direction == "ENTRY":
            # Person moving into store — emit ENTRY
            first_dt = tracker.get_first_event_time(visitor_id)
            if first_dt is None:
                first_dt = datetime.fromtimestamp(0, tz=timezone.utc)
            events.append(emit_entry(
                store_id, camera_id, visitor_id, first_dt,
                is_staff=is_staff, confidence=0.9, session_seq=1,
            ))
        elif direction == "EXIT":
            # Person moving out of store — emit EXIT
            last_dt = tracker.get_last_event_time(visitor_id)
            if last_dt is None:
                last_dt = datetime.utcnow()
            events.append(emit_exit(
                store_id, camera_id, visitor_id, last_dt,
                is_staff=is_staff, confidence=0.9, session_seq=1,
            ))

            # Check for re-entry: did this visitor re-enter recently?
            if tracker.check_reentry(visitor_id):
                events.append(emit_reentry(
                    store_id, camera_id, visitor_id, last_dt,
                    confidence=0.7, session_seq=2,
                ))
        else:
            # Direction unclear — emit ENTRY + EXIT as bookends
            first_dt = tracker.get_first_event_time(visitor_id)
            last_dt = tracker.get_last_event_time(visitor_id)
            if first_dt is None:
                first_dt = datetime.fromtimestamp(0, tz=timezone.utc)
            if last_dt is None:
                last_dt = datetime.utcnow()
            events.append(emit_entry(
                store_id, camera_id, visitor_id, first_dt,
                is_staff=is_staff, confidence=0.9, session_seq=1,
            ))
            events.append(emit_exit(
                store_id, camera_id, visitor_id, last_dt,
                is_staff=is_staff, confidence=0.9, session_seq=2,
            ))

    # ── Emit BILLING_QUEUE_ABANDON for visitors who joined but left ─
    billing_visitors = set()
    abandon_visitors = set()
    for evt in events:
        if evt["event_type"] == "BILLING_QUEUE_JOIN":
            billing_visitors.add(evt["visitor_id"])
        if evt["event_type"] == "ZONE_EXIT" and evt.get("zone_id") == "BILLING":
            if evt["visitor_id"] in billing_visitors:
                abandon_visitors.add(evt["visitor_id"])

    for vid in abandon_visitors:
        # Find the ZONE_EXIT time for this visitor from billing
        exit_evt = next(
            (e for e in events
             if e["event_type"] == "ZONE_EXIT"
             and e.get("zone_id") == "BILLING"
             and e["visitor_id"] == vid),
            None
        )
        if exit_evt:
            events.append(emit_billing_queue_abandon(
                store_id, camera_id, vid,
                datetime.fromisoformat(exit_evt["timestamp"].replace("Z", "+00:00")),
                confidence=0.8,
            ))

    # Sort all events by timestamp
    events.sort(key=lambda e: e["timestamp"])

    return events


# ──────────────────────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detection pipeline: CCTV footage → structured events"
    )
    parser.add_argument(
        "--clips-dir", default="./data/clips",
        help="Directory containing video clips (default: ./data/clips)",
    )
    parser.add_argument(
        "--store-layout", default="./data/store_layout.json",
        help="Path to store_layout.json (default: ./data/store_layout.json)",
    )
    parser.add_argument(
        "--output", default="./data/events.jsonl",
        help="Output JSONL file for events (default: ./data/events.jsonl)",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"YOLOv8 model size (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--conf-threshold", type=float, default=DEFAULT_CONF,
        help=f"Detection confidence threshold (default: {DEFAULT_CONF})",
    )
    args = parser.parse_args()

    if YOLO is None:
        print("ERROR: ultralytics not installed. Install with: pip install ultralytics")
        sys.exit(1)

    # Load YOLO model
    print(f"Loading YOLO model: {args.model}")
    model = YOLO(args.model)

    # Load store layout
    store_data = load_store_layout(args.store_layout)
    store_id = store_data["stores"][0]["store_id"]

    # Get camera configurations
    cameras = get_cameras(store_data)
    if not cameras:
        print("ERROR: No cameras found in store layout")
        sys.exit(1)

    clips_dir = Path(args.clips_dir)
    all_events: list[dict[str, Any]] = []

    for cam_config in cameras:
        camera_id = cam_config["camera_id"]
        clip_name = cam_config.get("clip", f"{camera_id}.mp4")
        clip_path = clips_dir / clip_name

        if not clip_path.exists():
            print(f"WARNING: Clip not found: {clip_path}")
            continue

        print(f"\nProcessing camera: {camera_id}")
        events = process_clip(
            str(clip_path), store_id, camera_id, store_data,
            model, args.conf_threshold,
        )
        print(f"  Generated {len(events)} events")
        all_events.extend(events)

    if not all_events:
        print("WARNING: No events generated from any clip")

    # Write output
    events_to_jsonl(all_events, args.output)
    print(f"\nTotal events: {len(all_events)}")
    print(f"Output written to: {args.output}")

    # Run validation
    print("\nRunning validation...")
    from pipeline.validate import validate_file, load_store_layout as load_layout  # noqa: E501
    known_stores, known_zones = load_layout(args.store_layout)
    total, valid, errors = validate_file(args.output, known_stores, known_zones)
    real_errors = [e for e in errors if e.severity == "ERROR"]
    warnings = [e for e in errors if e.severity == "WARN"]
    if warnings:
        print(f"Validation warnings: {len(warnings)}")
    if real_errors:
        print(f"Validation FAILED: {len(real_errors)} errors across "
              f"{total - valid} invalid events")
    else:
        print(f"Validation PASSED: {valid}/{total} events valid, "
              f"0 errors ({len(warnings)} warnings)")


if __name__ == "__main__":
    main()
