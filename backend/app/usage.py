"""Free-trial accounting for guests (anonymous Firebase users).

Each guest gets `guest_trials` AI requests. A per-IP daily cap stops people from getting fresh
trials by clearing their browser data, which creates a new anonymous account.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from app.auth import User

DAY_S = 86_400


@dataclass(frozen=True)
class TrialStatus:
    used: int
    limit: int
    allowed: bool

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used) if self.allowed else 0


class UsageTracker:
    def __init__(self, path: Path, guest_trials: int, ip_trials_per_day: int) -> None:
        self.path = path
        self.guest_trials = guest_trials
        self.ip_trials_per_day = ip_trials_per_day
        self._lock = threading.Lock()
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS guest_usage (uid TEXT PRIMARY KEY, used INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS ip_usage (ip TEXT NOT NULL, ts REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS ip_usage_ip ON ip_usage (ip, ts)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def _status(self, db: sqlite3.Connection, uid: str, ip: str) -> TrialStatus:
        row = db.execute("SELECT used FROM guest_usage WHERE uid = ?", (uid,)).fetchone()
        used = row[0] if row else 0
        ip_used = db.execute(
            "SELECT COUNT(*) FROM ip_usage WHERE ip = ? AND ts > ?", (ip, time.time() - DAY_S)
        ).fetchone()[0]
        allowed = used < self.guest_trials and ip_used < self.ip_trials_per_day
        return TrialStatus(used=used, limit=self.guest_trials, allowed=allowed)

    def status(self, user: User, ip: str) -> TrialStatus | None:
        """Trial status for guests and unverified accounts; None for members (no limit)."""
        if user.is_member:
            return None
        with self._lock, closing(self._connect()) as db:
            return self._status(db, user.uid, ip)

    def consume(self, user: User, ip: str) -> TrialStatus | None:
        """Use one trial. Returns the new status, or raises TrialExhausted. No-op for members."""
        if user.is_member:
            return None
        with self._lock, closing(self._connect()) as db, db:
            current = self._status(db, user.uid, ip)
            if not current.allowed:
                raise TrialExhausted(current)
            now = time.time()
            db.execute(
                "INSERT INTO guest_usage (uid, used) VALUES (?, 1) "
                "ON CONFLICT(uid) DO UPDATE SET used = used + 1",
                (user.uid,),
            )
            db.execute("INSERT INTO ip_usage (ip, ts) VALUES (?, ?)", (ip, now))
            db.execute("DELETE FROM ip_usage WHERE ts < ?", (now - DAY_S,))
            return self._status(db, user.uid, ip)


class TrialExhausted(Exception):
    def __init__(self, status: TrialStatus) -> None:
        super().__init__("Free trials used up")
        self.status = status
