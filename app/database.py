"""
SQLite connection management and schema initialization.
"""

import csv
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/store_intelligence.db")


def get_database() -> sqlite3.Connection:
    """Get SQLite connection with WAL mode enabled."""
    os.makedirs(os.path.dirname(DATABASE_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Create tables if they don't exist."""
    conn = get_database()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
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

            CREATE INDEX IF NOT EXISTS idx_events_store ON events(store_id);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

            CREATE TABLE IF NOT EXISTS pos_transactions (
                store_id TEXT NOT NULL,
                transaction_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                basket_value_inr REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pos_store ON pos_transactions(store_id);
            CREATE INDEX IF NOT EXISTS idx_pos_timestamp ON pos_transactions(timestamp);
        """)
        conn.commit()
    finally:
        conn.close()


def seed_pos_data():
    """
    Read data/pos_transactions.csv and insert into pos_transactions table.
    Skip if the table is already populated.
    """
    conn = get_database()
    try:
        # Check if already seeded
        cursor = conn.execute("SELECT COUNT(*) AS cnt FROM pos_transactions")
        row = cursor.fetchone()
        if row["cnt"] > 0:
            return

        csv_path = Path(__file__).parent.parent / "data" / "pos_transactions.csv"
        if not csv_path.exists():
            return

        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        conn.executemany(
            """
            INSERT OR IGNORE INTO pos_transactions (store_id, transaction_id, timestamp, basket_value_inr)
            VALUES (:store_id, :transaction_id, :timestamp, :basket_value_inr)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_database()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
