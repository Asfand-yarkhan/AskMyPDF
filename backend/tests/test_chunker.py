"""Unit tests for document analysis, adaptive chunk config and chunking."""

from __future__ import annotations

import re

import pymupdf as fitz
import pytest

from app.ingestion.analyzer import analyze_document, choose_chunk_config
from app.ingestion.chunker import chunk_document
from app.ingestion.loader import Block, ParsedDocument, ParsedPage, load_pdf

SENTENCE = "The mitochondria converts nutrients into usable cellular energy through respiration. "


def make_doc(pages: list[list[tuple[str, str]]], filename: str = "test.pdf") -> ParsedDocument:
    """pages: list of [(kind, text), ...]; headings set the running section."""
    parsed, section = [], None
    for number, blocks in enumerate(pages, start=1):
        page = ParsedPage(number=number)
        for kind, text in blocks:
            if kind == "heading":
                section = text
            page.blocks.append(Block(text=text, page=number, kind=kind, section=section))  # type: ignore[arg-type]
        parsed.append(page)
    return ParsedDocument(filename=filename, pages=parsed)


def prose_page(words: int, heading: str | None = None) -> list[tuple[str, str]]:
    sentences = [s for s in (SENTENCE * (words // 11 + 1)).split(". ") if s.strip()]
    paragraphs = [". ".join(sentences[i : i + 4]).strip() + "." for i in range(0, len(sentences), 4)]
    blocks = [("heading", heading)] if heading else []
    return blocks + [("text", p) for p in paragraphs if len(p) > 1]


# --- Strategy selection --------------------------------------------------------------


def test_short_document_uses_small_chunks() -> None:
    doc = make_doc([prose_page(300, "Intro"), prose_page(300), prose_page(300)])
    config = choose_chunk_config(analyze_document(doc))
    assert config.strategy == "short"
    assert (config.chunk_size, config.chunk_overlap) == (600, 120)


def test_slides_detected_by_low_word_density() -> None:
    doc = make_doc([[("heading", f"Slide {i}"), ("text", "Revenue grew 12% year over year.")] for i in range(12)])
    profile = analyze_document(doc)
    config = choose_chunk_config(profile)
    assert profile.avg_words_per_page < 120
    assert config.strategy == "slides"
    assert config.chunk_overlap == 0


def test_general_report() -> None:
    doc = make_doc([prose_page(350, f"Chapter {i}") for i in range(15)])
    config = choose_chunk_config(analyze_document(doc))
    assert config.strategy == "general"
    assert config.chunk_size == 1000
    assert 150 <= config.chunk_overlap <= 200


def test_technical_document() -> None:
    legal = (
        "Abstract. Pursuant to clause 4 of Article 12, whereas the parties agree herein, the algorithm "
        "parameters in Section 3.2 follow the methodology of Smith et al. [1] and Theorem 2 (doi 10.1/x). "
    )
    pages = [[("text", legal * 8)] for _ in range(14)]
    config = choose_chunk_config(analyze_document(make_doc(pages)))
    assert config.strategy == "technical"
    assert 1200 <= config.chunk_size <= 1500
    assert 200 <= config.chunk_overlap <= 250


@pytest.mark.parametrize("pages", [3, 15])
def test_overlap_is_15_to_20_percent(pages: int) -> None:
    doc = make_doc([prose_page(350, f"H{i}") for i in range(pages)])
    config = choose_chunk_config(analyze_document(doc))
    assert 0.15 <= config.chunk_overlap / config.chunk_size <= 0.20


# --- Chunking -----------------------------------------------------------------------------


def test_chunks_respect_size_and_carry_metadata() -> None:
    doc = make_doc([prose_page(400, f"Section {i}") for i in range(12)])
    config = choose_chunk_config(analyze_document(doc))
    chunks = chunk_document(doc, config, "abc123")
    assert chunks
    for i, chunk in enumerate(chunks):
        assert len(chunk.text) <= config.chunk_size
        meta = chunk.metadata
        assert meta["chunk_index"] == i
        assert meta["chunk_id"] == f"abc123-{i:05d}"
        assert meta["doc_id"] == "abc123"
        assert 1 <= meta["page"] <= meta["page_end"] <= 12
        assert isinstance(meta["section"], str)
        assert all(v is not None for v in meta.values())


def test_chunks_do_not_cut_mid_sentence() -> None:
    doc = make_doc([prose_page(500, "Energy")] * 12)
    chunks = chunk_document(doc, choose_chunk_config(analyze_document(doc)), "d1")
    endings = [c.text.rstrip()[-1] for c in chunks]
    # Every chunk should end at a sentence boundary (or a heading line).
    assert sum(e in ".?!" for e in endings) >= len(chunks) - 1


def test_pages_map_to_chunks_in_order() -> None:
    doc = make_doc([[("text", f"Page {n} fact number {n}. " * 30)] for n in range(1, 13)])
    chunks = chunk_document(doc, choose_chunk_config(analyze_document(doc)), "d2")
    pages = [c.metadata["page"] for c in chunks]
    assert pages == sorted(pages)
    for chunk in chunks:
        first_page = int(re.search(r"Page (\d+)", chunk.text).group(1))
        assert chunk.metadata["page"] <= first_page <= chunk.metadata["page_end"]


def test_section_metadata_follows_headings() -> None:
    doc = make_doc([prose_page(300, "Photosynthesis"), prose_page(300, "Respiration")])
    chunks = chunk_document(doc, choose_chunk_config(analyze_document(doc)), "d3")
    assert chunks[0].metadata["section"] == "Photosynthesis"
    assert chunks[-1].metadata["section"] == "Respiration"


def test_small_table_stays_whole_and_inline() -> None:
    table = "| Name | Score |\n| --- | --- |\n| Ali | 90 |\n| Sara | 85 |"
    caption = [("heading", "Results"), ("text", "Table 1 shows the final scores of both students.")]
    doc = make_doc([prose_page(300) + caption + [("table", table)] + prose_page(100)])
    config = choose_chunk_config(analyze_document(doc))
    assert config.chunk_size >= 1000  # tables raise the chunk size so captions and totals fit
    chunks = chunk_document(doc, config, "d4")
    holders = [c for c in chunks if "| Ali | 90 |" in c.text]
    assert holders and all(table in c.text for c in holders)  # never cut inside the table
    assert all(c.metadata["has_table"] is True for c in holders)
    assert "Table 1 shows" in holders[0].text  # its caption travels with it


def test_totals_after_table_stay_with_table_across_page_break() -> None:
    """A results card: header -> table -> 'CGPA: x' on the next page -> next header. The totals line
    must sit after its own table, and never be glued to the next semester's header alone."""
    def semester(name: str, cgpa: str) -> list[tuple[str, str]]:
        return [
            ("text", "Reg. No: 123 Name: ASFAND"),
            ("text", f"Semester: {name} Father Name: X"),
            ("table", "| Course | Marks |\n| --- | --- |\n| CSC101 | 85 |\n| HUM100 | 90 |\n| MTH091 | 78 |"),
            ("text", f"CGPA : {cgpa}"),
            ("text", "Scholastic Status: GAS"),
        ]
    page1 = semester("Spring 2025", "3.68")[:-2]  # CGPA + status spill to page 2
    page2 = semester("Spring 2025", "3.68")[-2:] + semester("Fall 2025", "3.47")
    doc = make_doc([page1, page2])
    chunks = chunk_document(doc, choose_chunk_config(analyze_document(doc)), "d5")
    holder = next(c for c in chunks if "CGPA : 3.68" in c.text)
    assert "Semester: Spring 2025" in holder.text and "| CSC101 | 85 |" in holder.text
    assert holder.text.index("| MTH091 | 78 |") < holder.text.index("CGPA : 3.68")
    assert holder.metadata["page"] == 1 and holder.metadata["page_end"] == 2
    # The page break is recorded so the LLM sees where page 2 starts inside the chunk.
    offset, page = holder.metadata["page_breaks"].split(";")[0].split(":")
    assert page == "2" and holder.text[int(offset):].startswith("CGPA : 3.68")


def test_huge_table_split_by_rows_with_header() -> None:
    rows = "\n".join(f"| item {i} | {'x' * 60} |" for i in range(200))
    table = "| Item | Value |\n| --- | --- |\n" + rows
    doc = make_doc([[("table", table)]])
    chunks = [c for c in chunk_document(doc, choose_chunk_config(analyze_document(doc)), "d5")]
    assert len(chunks) > 1
    assert all(c.text.startswith("| Item | Value |") for c in chunks)


def test_slides_one_chunk_per_slide() -> None:
    doc = make_doc([[("heading", f"Slide {i}"), ("text", "Short bullet point.")] for i in range(10)])
    config = choose_chunk_config(analyze_document(doc))
    chunks = chunk_document(doc, config, "d6")
    assert len(chunks) == 10
    assert [c.metadata["page"] for c in chunks] == list(range(1, 11))
    assert chunks[3].metadata["section"] == "Slide 3"


# --- Loader (real PDF built in memory) ------------------------------------------------------------


def test_loader_strips_repeated_headers_and_ignores_label_lines() -> None:
    pdf = fitz.open()
    for n in range(1, 5):
        page = pdf.new_page()
        page.insert_text((72, 40), "7/8/26, 3:06 PM", fontsize=9)
        page.insert_text((300, 40), "CUOnline Student Portal", fontsize=9)
        if n == 1:
            page.insert_text((72, 80), "Student Result Card", fontsize=16)
        page.insert_text((72, 110), f"Semester: Term {n}", fontsize=11, fontname="hebo")
        page.insert_text((72, 130), f"Course text for term {n} goes here.", fontsize=11)
        page.insert_text((72, 150), f"CGPA : 3.{80 + n}", fontsize=11, fontname="hebo")
        page.insert_text((72, 780), f"https://portal.example.edu/ResultCard  {n}/4", fontsize=8)
    parsed = load_pdf(pdf.tobytes(), "card.pdf", ocr_enabled=False)
    text = "\n".join(b.text for b in parsed.blocks)
    assert "CUOnline Student Portal" not in text and "3:06 PM" not in text and "ResultCard" not in text
    # Body lines that share a layout position but carry different content are kept.
    assert all(f"Semester: Term {n}" in text and f"CGPA : 3.{80 + n}" in text for n in range(1, 5))
    headings = {b.text for b in parsed.blocks if b.kind == "heading"}
    assert headings == {"Student Result Card"}  # bold "Label: value" lines are not headings


def test_loader_detects_headings_and_pages() -> None:
    pdf = fitz.open()
    for title in ("Introduction", "Methods"):
        page = pdf.new_page()
        page.insert_text((72, 80), title, fontsize=20)
        y = 120
        for _ in range(5):
            page.insert_text((72, y), "This is ordinary body text describing the study.", fontsize=11)
            y += 16
    data = pdf.tobytes()

    parsed = load_pdf(data, "sample.pdf", ocr_enabled=False)
    assert parsed.page_count == 2
    headings = [b.text for b in parsed.blocks if b.kind == "heading"]
    assert headings == ["Introduction", "Methods"]
    body = [b for b in parsed.pages[1].blocks if b.kind == "text"]
    assert body and body[0].section == "Methods"
