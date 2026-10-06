"""Document profiling and adaptive chunk-config selection."""

from __future__ import annotations

import re

from app.ingestion.loader import ParsedDocument
from app.schemas import ChunkConfig, DocumentProfile

_BULLET = re.compile(r"^\s*([•\-\*▪◦●–]|\d{1,2}[\.\)])\s+")

# Signals of research papers, legal texts and technical manuals.
_TECHNICAL_SIGNALS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\babstract\b", r"\breferences\b", r"\bbibliography\b", r"\bet al\.", r"\bdoi\b",
        r"\[\d+(?:,\s*\d+)*\]", r"\bmethodology\b", r"\btheorem\b", r"\blemma\b", r"\bequation\b",
        r"\bhypothes[ie]s\b", r"\bhereinafter\b", r"\bpursuant\b", r"\bwhereas\b", r"\bclause\b",
        r"\bjurisdiction\b", r"\bindemnif", r"\bherein\b", r"\bspecification\b", r"\balgorithm\b",
        r"\bparameters?\b", r"\barticle\s+\d+", r"\bsection\s+\d+(\.\d+)*",
    )
)

SLIDES_MAX_WORDS_PER_PAGE = 120
SHORT_DOC_MAX_PAGES = 10
NOTES_MIN_BULLET_RATIO = 0.35
TECHNICAL_MIN_SCORE = 5
SAMPLE_PAGES = 40


def analyze_document(doc: ParsedDocument) -> DocumentProfile:
    page_count = max(doc.page_count, 1)
    total_words = sum(p.word_count for p in doc.pages)
    headings = [b for b in doc.blocks if b.kind == "heading"]
    text_blocks = [b for b in doc.blocks if b.kind == "text"]
    table_count = sum(p.table_count for p in doc.pages)
    pages_with_tables = sum(1 for p in doc.pages if p.table_count)
    bullet_items = sum(
        1 for b in text_blocks for line in b.text.splitlines() if _BULLET.match(line)
    )
    bullet_lines = sum(len(b.text.splitlines()) for b in text_blocks)
    ocr_pages = sum(1 for p in doc.pages if p.is_ocr)

    sample = " ".join(p.text for p in doc.pages[:SAMPLE_PAGES])
    technical_score = sum(1 for pattern in _TECHNICAL_SIGNALS if pattern.search(sample))

    profile = DocumentProfile(
        page_count=doc.page_count,
        total_words=total_words,
        avg_words_per_page=round(total_words / page_count, 1),
        heading_count=len(headings),
        heading_density=round(len(headings) / page_count, 2),
        table_count=table_count,
        table_ratio=round(pages_with_tables / page_count, 2),
        bullet_ratio=round(bullet_items / bullet_lines, 2) if bullet_lines else 0.0,
        ocr_pages=ocr_pages,
        is_scanned=ocr_pages > page_count * 0.5,
        technical_score=technical_score,
        doc_type="",
    )
    profile.doc_type = classify(profile)
    return profile


def classify(p: DocumentProfile) -> str:
    if p.page_count >= 3 and 0 < p.avg_words_per_page < SLIDES_MAX_WORDS_PER_PAGE and not p.is_scanned:
        return "slides"
    if p.bullet_ratio >= NOTES_MIN_BULLET_RATIO:
        return "notes"
    if p.page_count < SHORT_DOC_MAX_PAGES:
        return "short"
    if p.technical_score >= TECHNICAL_MIN_SCORE or (p.technical_score >= 3 and p.avg_words_per_page > 550):
        return "technical"
    return "general"


TABLE_MIN_CHUNK = 1000  # a table plus its caption and totals rarely fits in less


def choose_chunk_config(p: DocumentProfile) -> ChunkConfig:
    """Map the document profile to a chunk size/overlap (overlap kept at roughly 15-20%)."""
    config = _base_config(p)
    if p.table_count > 0 and config.strategy != "slides" and config.chunk_size < TABLE_MIN_CHUNK:
        config.chunk_size, config.chunk_overlap = TABLE_MIN_CHUNK, 160
        config.reason += f" Raised to {TABLE_MIN_CHUNK} chars so tables keep their captions and totals."
    return config


def _base_config(p: DocumentProfile) -> ChunkConfig:
    doc_type = p.doc_type or classify(p)
    if doc_type == "slides":
        return ChunkConfig(
            strategy="slides", chunk_size=1500, chunk_overlap=0,
            reason=(f"Avg {p.avg_words_per_page:.0f} words/page looks like a slide deck: "
                    "one slide = one chunk, no overlap (very long slides are split at 1500 chars)."),
        )
    if doc_type == "notes":
        return ChunkConfig(
            strategy="notes", chunk_size=600, chunk_overlap=120,
            reason=f"{p.bullet_ratio:.0%} of lines are list items (notes-style): small 600-char chunks.",
        )
    if doc_type == "short":
        return ChunkConfig(
            strategy="short", chunk_size=600, chunk_overlap=120,
            reason=f"Short document ({p.page_count} pages): small 600-char chunks for precise retrieval.",
        )
    if doc_type == "technical":
        dense = p.avg_words_per_page > 500
        size, overlap = (1500, 250) if dense else (1200, 200)
        return ChunkConfig(
            strategy="technical", chunk_size=size, chunk_overlap=overlap,
            reason=(f"Research/legal/technical signals (score {p.technical_score}): larger chunks keep "
                    "arguments, clauses and definitions intact."),
        )
    overlap = 200 if p.avg_words_per_page > 450 else 160
    return ChunkConfig(
        strategy="general", chunk_size=1000, chunk_overlap=overlap,
        reason=f"Regular report/book ({p.page_count} pages, ~{p.avg_words_per_page:.0f} words/page).",
    )
