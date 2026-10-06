"""Tiny JSON-backed registry of ingested documents (metadata for GET /documents)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from app.schemas import DocumentInfo

logger = logging.getLogger(__name__)


class DocumentRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._docs: dict[str, DocumentInfo] = self._load()

    def _load(self) -> dict[str, DocumentInfo]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {k: DocumentInfo.model_validate(v) for k, v in raw.items()}
        except Exception:
            logger.exception("Registry at %s is unreadable; starting empty", self.path)
            return {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        payload = {k: v.model_dump(mode="json") for k, v in self._docs.items()}
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic on POSIX and Windows

    def get(self, doc_id: str) -> DocumentInfo | None:
        with self._lock:
            return self._docs.get(doc_id)

    def list(self) -> list[DocumentInfo]:
        with self._lock:
            return sorted(self._docs.values(), key=lambda d: d.created_at, reverse=True)

    def upsert(self, info: DocumentInfo) -> None:
        with self._lock:
            self._docs[info.doc_id] = info
            self._save()

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            existed = self._docs.pop(doc_id, None) is not None
            if existed:
                self._save()
            return existed
