#!/bin/bash
set -euo pipefail

CLIPS_DIR="${1:-./data/clips}"
OUTPUT="${2:-./data/events.jsonl}"
STORE_LAYOUT="${3:-./data/store_layout.json}"

echo "=== Store Intelligence Detection Pipeline ==="
echo "Clips dir:    $CLIPS_DIR"
echo "Output:       $OUTPUT"
echo "Store layout: $STORE_LAYOUT"
echo ""

# Run detection
python pipeline/detect.py \
    --clips-dir "$CLIPS_DIR" \
    --store-layout "$STORE_LAYOUT" \
    --output "$OUTPUT" \
    --model yolov8m \
    --conf-threshold 0.35

# Validate output
echo ""
echo "=== Validating output ==="
python pipeline/validate.py "$OUTPUT" --layout "$STORE_LAYOUT"

echo ""
echo "=== Done ==="
