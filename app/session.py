"""
In-memory session manager for visitor tracking.
"""

import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field


@dataclass
class VisitorSession:
    visitor_id: str
    store_id: str
    entry_time: datetime
    exit_time: datetime | None = None
    is_staff: bool = False
    zones_visited: list[str] = field(default_factory=list)
    converted: bool = False
    billing_entry_time: datetime | None = None


class SessionManager:
    """Thread-safe in-memory session manager for visitor tracking."""

    def __init__(self):
        self._sessions: dict[str, VisitorSession] = {}
        self._last_exit_time: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def create_session(self, visitor_id: str, store_id: str,
                       entry_event: dict) -> VisitorSession:
        """Create a new session for a visitor on entry.

        Preserves the last exit_time for re-entry detection.
        """
        entry_time = datetime.fromisoformat(entry_event["timestamp"].replace("Z", "+00:00"))
        with self._lock:
            # Preserve exit_time before overwriting
            existing = self._sessions.get(visitor_id)
            if existing and existing.exit_time is not None:
                self._last_exit_time[visitor_id] = existing.exit_time
            session = VisitorSession(
                visitor_id=visitor_id,
                store_id=store_id,
                entry_time=entry_time,
                is_staff=entry_event.get("is_staff", False),
            )
            self._sessions[visitor_id] = session
            return session

    def get_session(self, visitor_id: str) -> VisitorSession | None:
        """Get the current session for a visitor."""
        with self._lock:
            return self._sessions.get(visitor_id)

    def close_session(self, visitor_id: str, exit_event: dict):
        """Mark a visitor's session as exited."""
        exit_time = datetime.fromisoformat(exit_event["timestamp"].replace("Z", "+00:00"))
        with self._lock:
            session = self._sessions.get(visitor_id)
            if session:
                session.exit_time = exit_time

    def check_reentry(self, visitor_id: str, entry_time: datetime,
                      time_window_minutes: int = 5) -> bool:
        """Check if a visitor re-entered within the given time window.

        Checks both the current session's exit_time and the last known
        exit_time (preserved across session resets).
        """
        with self._lock:
            session = self._sessions.get(visitor_id)
            # Check current session first
            if session and session.exit_time:
                gap = (entry_time - session.exit_time).total_seconds() / 60
                if gap <= time_window_minutes:
                    return True
            # Check preserved last exit time
            last_exit = self._last_exit_time.get(visitor_id)
            if last_exit:
                gap = (entry_time - last_exit).total_seconds() / 60
                return gap <= time_window_minutes
            return False

    def update_billing_entry(self, visitor_id: str, timestamp: datetime):
        """Record when a visitor entered the billing zone."""
        with self._lock:
            session = self._sessions.get(visitor_id)
            if session:
                session.billing_entry_time = timestamp

    def is_converted(self, visitor_id: str, pos_transactions: list[dict],
                     window_minutes: int = 5) -> bool:
        """Check if visitor was in billing zone within window_minutes of a POS txn.

        Per the plan: "A visitor who was in the billing zone in the 5-minute
        window before a transaction timestamp counts as converted."
        """
        with self._lock:
            session = self._sessions.get(visitor_id)
            if not session or not session.billing_entry_time:
                return False
            for txn in pos_transactions:
                txn_time = datetime.fromisoformat(txn["timestamp"].replace("Z", "+00:00"))
                diff = (txn_time - session.billing_entry_time).total_seconds()
                if 0 <= diff <= window_minutes * 60:
                    return True
            return False
