"""
PROMPT: Generate tests for database initialization, POS seeding, and connection management.

CHANGES MADE: None (AI-generated tests for database).
"""

import sqlite3

import pytest
from app.database import get_database, init_database, seed_pos_data, get_db


class TestDatabaseConnection:
    def test_get_database_returns_sqlite_connection(self, temp_db):
        conn = get_database()
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_init_database_creates_tables(self, temp_db):
        conn = get_database()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [r["name"] for r in tables]
        assert "events" in table_names
        assert "pos_transactions" in table_names
        conn.close()

    def test_init_database_idempotent(self, temp_db):
        """Calling init_database twice should not raise."""
        init_database()  # Second call
        conn = get_database()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) >= 2
        conn.close()


class TestSeedPosData:
    def test_seed_pos_data_populates_table(self, temp_db):
        seed_pos_data()
        conn = get_database()
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM pos_transactions"
        ).fetchone()["cnt"]
        assert count > 0
        conn.close()

    def test_seed_pos_data_idempotent(self, temp_db):
        """Seeding twice should not duplicate rows."""
        seed_pos_data()
        seed_pos_data()
        conn = get_database()
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM pos_transactions"
        ).fetchone()["cnt"]
        assert count > 0
        conn.close()


class TestGetDbContextManager:
    def test_get_db_yields_connection(self, temp_db):
        with get_db() as conn:
            assert isinstance(conn, sqlite3.Connection)
            conn.execute("SELECT 1")

    def test_get_db_commits_on_success(self, temp_db):
        with get_db() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS test_commit (id INTEGER)"
            )
        # After context exit, the table should exist (committed)
        conn2 = get_database()
        tables = [r["name"] for r in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "test_commit" in tables
        conn2.close()
