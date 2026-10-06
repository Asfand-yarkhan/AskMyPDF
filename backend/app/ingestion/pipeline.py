"""End-to-end ingestion: hash -> parse -> analyze -> chunk -> embed -> register."""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from app.config import Settings
from app.ingestion.analyzer import analyze_document, choose_chunk_config
from app.ingestion.chunker import chunk_document
from app.ingestion.loader import PDFParseError, load_pdf
from app.registry import DocumentRegistry
from app.schemas import DocumentInfo
from app.vectorstore import VectorStoreManager

logger = logging.getLogger(__name__)

# (stage, progress 0..1, human readable message)
ProgressFn = Callable[[str, float, str], None]

_doc_locks: dict[str, threading.Lock] = {}
_doc_locks_guard = threading.Lock()


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:24]


def _lock_for(doc_id: str) -> threading.Lock:
    with _doc_locks_guard:
        return _doc_locks.setdefault(doc_id, threading.Lock())


def ingest_pdf(
    data: bytes,
    filename: str,
    *,
    settings: Settings,
    vectorstore: VectorStoreManager,
    registry: DocumentRegistry,
    progress: ProgressFn | None = None,
) -> tuple[DocumentInfo, bool]:
    """Ingest a PDF. Returns (info, reused) where reused=True means embeddings already existed."""
    report = progress or (lambda *_: None)
    doc_id = file_hash(data)

    with _lock_for(doc_id):  # the same file uploaded twice concurrently is embedded once
        existing = registry.get(doc_id)
        if (
            existing
            and existing.embedding_id == settings.embedding_id
            and vectorstore.count(doc_id) == existing.chunk_count
        ):
            logger.info("Reusing embeddings for %s (%s)", filename, doc_id)
            report("done", 1.0, "Already indexed. Reusing existing embeddings.")
            return existing, True

        report("parsing", 0.05, "Reading pages, headings and tables...")
        parsed = load_pdf(
            data,
            filename,
            ocr_enabled=settings.ocr_enabled,
            ocr_language=settings.ocr_language,
            tesseract_cmd=settings.tesseract_cmd,
        )

        report("analyzing", 0.25, "Analyzing document structure...")
        profile = analyze_document(parsed)
        config = choose_chunk_config(profile)
        logger.info("%s profile=%s config=%s", filename, profile.model_dump(), config.model_dump())

        report("chunking", 0.35, f"Chunking with the '{config.strategy}' strategy...")
        chunks = chunk_document(parsed, config, doc_id)
        if not chunks:
            hint = " Install Tesseract to enable OCR for scanned PDFs." if profile.ocr_pages == 0 else ""
            raise PDFParseError("No extractable text found in this PDF." + hint)

        vectorstore.delete(doc_id)  # drop stale vectors (e.g. a different embedding model)
        report("embedding", 0.4, f"Embedding {len(chunks)} chunks...")

        def on_embed(done: int, total: int) -> None:
            report("embedding", 0.4 + 0.55 * done / total, f"Embedded {done}/{total} chunks")

        vectorstore.add_chunks(doc_id, chunks, on_embed)

        (settings.upload_dir / f"{doc_id}.pdf").write_bytes(data)
        info = DocumentInfo(
            doc_id=doc_id,
            filename=filename,
            size_bytes=len(data),
            page_count=parsed.page_count,
            chunk_count=len(chunks),
            total_chars=sum(len(c.text) for c in chunks),
            created_at=datetime.now(timezone.utc),
            chunk_config=config,
            profile=profile,
            embedding_id=settings.embedding_id,
        )
        registry.upsert(info)
        report("done", 1.0, "Ready to chat!")
        return info, False
