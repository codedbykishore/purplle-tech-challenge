#!/usr/bin/env python3
"""
Parse the original POS CSV from docs/ and produce data/pos_transactions.csv
in the required schema: store_id, transaction_id, timestamp, basket_value_inr

Mapping:
  - store_id -> "STORE_BLR_002" (hardcoded)
  - transaction_id -> "TXN_" + order_id
  - timestamp -> combine order_date (DD-MM-YYYY) + order_time (HH:MM:SS), IST->UTC (-5:30)
  - basket_value_inr -> total_amount
"""

import csv
from datetime import datetime, timedelta

INPUT = "docs/Brigade_Bangalore_10_April_26 (1)bc6219c.csv"
OUTPUT = "data/pos_transactions.csv"

IST_OFFSET = timedelta(hours=5, minutes=30)

# Store_id to use (ST1008 in source -> STORE_BLR_002 as required)
TARGET_STORE = "STORE_BLR_002"

def parse_timestamp(date_str: str, time_str: str) -> str:
    """Parse DD-MM-YYYY and HH:MM:SS, convert IST to UTC, return ISO-8601."""
    dt_ist = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S")
    dt_utc = dt_ist - IST_OFFSET
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

def main():
    with open(INPUT, newline="", encoding="utf-8") as inf, \
         open(OUTPUT, "w", newline="", encoding="utf-8") as outf:

        reader = csv.DictReader(inf)
        writer = csv.writer(outf)

        # Write header
        writer.writerow(["store_id", "transaction_id", "timestamp", "basket_value_inr"])

        seen_txns = set()
        for row in reader:
            order_id = row["order_id"].strip()
            if not order_id:
                continue

            # Deduplicate order_id (same order can have multiple lines)
            if order_id in seen_txns:
                continue
            seen_txns.add(order_id)

            date_str = row["order_date"].strip()
            time_str = row["order_time"].strip()

            try:
                ts = parse_timestamp(date_str, time_str)
            except ValueError as e:
                print(f"WARN: Skipping order {order_id}: {e}")
                continue

            try:
                basket_val = float(row["total_amount"].strip())
            except (ValueError, KeyError):
                basket_val = 0.0

            txn_id = f"TXN_{order_id}"
            writer.writerow([TARGET_STORE, txn_id, ts, f"{basket_val:.2f}"])

    print(f"Written {len(seen_txns)} transactions to {OUTPUT}")

if __name__ == "__main__":
    main()
