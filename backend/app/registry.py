"""Tiny JSON-backed registry of ingested documents and the users who own them.

Documents are keyed by content hash, so two users uploading the same PDF share one index;
each keeps it until they delete it, and the files are purged when the last owner does.
"""

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
        self._docs: dict[str, DocumentInfo] = {}
        self._owners: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if "documents" not in raw:  # format before accounts: {doc_id: info}, no owners
                raw = {"documents": raw, "owners": {}}
            self._docs = {k: DocumentInfo.model_validate(v) for k, v in raw["documents"].items()}
            self._owners = {k: set(v) for k, v in raw.get("owners", {}).items() if k in self._docs}
        except Exception:
            logger.exception("Registry at %s is unreadable; starting empty", self.path)

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        payload = {
            "documents": {k: v.model_dump(mode="json") for k, v in self._docs.items()},
            "owners": {k: sorted(v) for k, v in self._owners.items() if v},
        }
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic on POSIX and Windows

    def get(self, doc_id: str) -> DocumentInfo | None:
        with self._lock:
            return self._docs.get(doc_id)

    def list(self, owner: str | None = None) -> list[DocumentInfo]:
        """All documents, or only those `owner` can see."""
        with self._lock:
            docs = [d for d in self._docs.values() if owner is None or owner in self._owners.get(d.doc_id, ())]
        return sorted(docs, key=lambda d: d.created_at, reverse=True)

    def is_owner(self, doc_id: str, owner: str) -> bool:
        with self._lock:
            return owner in self._owners.get(doc_id, ())

    def upsert(self, info: DocumentInfo) -> None:
        with self._lock:
            self._docs[info.doc_id] = info
            self._save()

    def add_owner(self, doc_id: str, owner: str) -> None:
        with self._lock:
            if doc_id in self._docs and owner not in self._owners.setdefault(doc_id, set()):
                self._owners[doc_id].add(owner)
                self._save()

    def remove_owner(self, doc_id: str, owner: str) -> bool:
        """Drop one owner. Returns True when nobody owns the document any more."""
        with self._lock:
            owners = self._owners.get(doc_id, set())
            owners.discard(owner)
            if owners:
                self._save()
                return False
            self._owners.pop(doc_id, None)
            return True

    def transfer_owner(self, old: str, new: str) -> int:
        """Give `new` every document `old` owns (a guest signing in to an existing account)."""
        with self._lock:
            moved = 0
            for owners in self._owners.values():
                if old in owners:
                    owners.discard(old)
                    owners.add(new)
                    moved += 1
            if moved:
                self._save()
            return moved

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            existed = self._docs.pop(doc_id, None) is not None
            self._owners.pop(doc_id, None)
            if existed:
                self._save()
            return existed
