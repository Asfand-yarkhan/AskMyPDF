"""SQLite cache for expensive, repeatable answers (summaries, notes, history-free questions).

Keys include each document's id *and* ingestion timestamp plus the model names, so re-uploading
a document or switching models never serves a stale answer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def make_key(**parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_question(text: str) -> str:
    return " ".join(text.lower().split()).rstrip("?.! ")


class ResponseCache:
    def __init__(self, path: Path, ttl_hours: int, enabled: bool = True) -> None:
        self.enabled = enabled
        self.ttl_s = ttl_hours * 3600
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " key TEXT PRIMARY KEY, doc_ids TEXT NOT NULL, created REAL NOT NULL, events TEXT NOT NULL)"
        )
        self._db.commit()

    def get(self, key: str) -> list[dict[str, Any]] | None:
        if not self.enabled:
            return None
        with self._lock:
            row = self._db.execute("SELECT created, events FROM responses WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if time.time() - row[0] >= self.ttl_s:
            self._delete_key(key)
            return None
        return json.loads(row[1])

    def put(self, key: str, doc_ids: list[str], events: list[dict[str, Any]]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO responses (key, doc_ids, created, events) VALUES (?, ?, ?, ?)",
                (key, ",".join(doc_ids), time.time(), json.dumps(events, ensure_ascii=False)),
            )
            self._db.commit()

    def forget_document(self, doc_id: str) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM responses WHERE ',' || doc_ids || ',' LIKE ?", (f"%,{doc_id},%",))
            self._db.commit()
            return cur.rowcount

    def _delete_key(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM responses WHERE key = ?", (key,))
            self._db.commit()
