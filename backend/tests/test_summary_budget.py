"""Token-budgeted summaries and the upload page limit."""

from __future__ import annotations

import pymupdf
import pytest
from langchain_core.documents import Document

from app.chains.summary import group_texts, select_within_budget
from app.config import Settings
from app.ingestion.loader import PDFParseError, count_pages
from app.ingestion.pipeline import ingest_pdf


def make_docs(n: int, size: int = 1000, sections: int = 10) -> list[Document]:
    return [
        Document(
            page_content="x" * size,
            metadata={"chunk_index": i, "page": i // 3 + 1, "section": f"Section {i * sections // n}"},
        )
        for i in range(n)
    ]


def test_small_document_is_used_whole() -> None:
    docs = make_docs(10)
    assert select_within_budget(docs, 24_000) == docs


def test_large_document_fits_budget_and_covers_every_section() -> None:
    docs = make_docs(150)  # 150k chars, like a 40-page report
    chosen = select_within_budget(docs, 24_000)
    assert sum(len(d.page_content) for d in chosen) <= 24_000
    assert {d.metadata["section"] for d in chosen} == {f"Section {i}" for i in range(10)}
    indexes = [d.metadata["chunk_index"] for d in chosen]
    assert indexes == sorted(indexes)  # reading order
    assert indexes[-1] > 120  # reaches the end of the document, not just the start


def test_group_texts_respects_target() -> None:
    groups = group_texts(["a" * 5000] * 5, 12_000)
    assert len(groups) == 3
    assert all(len(g) <= 12_010 for g in groups)


def _pdf_with_pages(n: int) -> bytes:
    pdf = pymupdf.open()
    for i in range(n):
        pdf.new_page().insert_text((72, 72), f"Page {i + 1} text.")
    return pdf.tobytes()


def test_count_pages() -> None:
    assert count_pages(_pdf_with_pages(7)) == 7


def test_upload_rejected_over_page_limit(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, max_pages=5)
    with pytest.raises(PDFParseError, match="limit is 5"):
        ingest_pdf(
            _pdf_with_pages(6), "big.pdf", settings=settings,
            vectorstore=None, registry=_EmptyRegistry(),  # type: ignore[arg-type]
        )


class _EmptyRegistry:
    def get(self, _doc_id: str) -> None:
        return None
