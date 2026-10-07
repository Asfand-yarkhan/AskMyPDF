"""Context formatting: page markers inside multi-page chunks."""

from __future__ import annotations

from langchain_core.documents import Document

from app.chains.common import format_context, with_page_markers


def test_page_markers_inserted_at_breaks() -> None:
    doc = Document(
        page_content="Semester: Spring 2025\n| table |\nCGPA : 3.68\nSemester: Fall 2025",
        metadata={"page": 3, "page_end": 4, "page_breaks": "32:4", "has_table": True},
    )
    marked = with_page_markers(doc)
    assert marked == "Semester: Spring 2025\n| table |\n[p. 4]\nCGPA : 3.68\nSemester: Fall 2025"
    context = format_context([doc])
    assert context.startswith("[p. 3] | table\n")


def test_no_breaks_leaves_text_untouched() -> None:
    doc = Document(page_content="plain text", metadata={"page": 1, "page_breaks": ""})
    assert with_page_markers(doc) == "plain text"
