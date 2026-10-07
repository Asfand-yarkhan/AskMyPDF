"""PDF parsing with PyMuPDF: page-wise text blocks, heading detection, tables, OCR fallback."""

from __future__ import annotations

import io
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

import pymupdf as fitz

logger = logging.getLogger(__name__)

BlockKind = Literal["heading", "text", "table"]

_NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.|chapter\s+\w+|section\s+\w+|part\s+\w+)\s+\S", re.I)
_ONLY_NUMBERS_OR_PUNCT = re.compile(r"^[\d\W_]+$")
# "CGPA : 3.87", "Reg. No: 123", "Date: 7/8/26" are labels with values, not section headings.
_LABEL_VALUE = re.compile(r"^[A-Za-z][\w .()/-]{0,40}\s*:\s*\S")
_EDGE_LINES = 3  # lines at the top/bottom of a page checked for repeated headers/footers
_DIGITS = re.compile(r"\d+")
_OCR_MIN_WORDS = 10


class PDFParseError(Exception):
    """Raised when a PDF cannot be opened or contains no usable content."""


@dataclass
class Block:
    text: str
    page: int
    kind: BlockKind
    section: str | None = None


@dataclass
class ParsedPage:
    number: int  # 1-based
    blocks: list[Block] = field(default_factory=list)
    is_ocr: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    @property
    def word_count(self) -> int:
        return sum(len(b.text.split()) for b in self.blocks)

    @property
    def table_count(self) -> int:
        return sum(1 for b in self.blocks if b.kind == "table")


@dataclass
class ParsedDocument:
    filename: str
    pages: list[ParsedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def blocks(self) -> list[Block]:
        return [b for p in self.pages for b in p.blocks]


@dataclass
class _Line:
    text: str
    size: float
    bold: bool


@dataclass
class _RawBlock:
    lines: list[_Line]
    bbox: tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def count_pages(data: bytes) -> int:
    """Page count without parsing content (used to reject oversized uploads early)."""
    try:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            return pdf.page_count
    except Exception as exc:
        raise PDFParseError(f"Could not open PDF: {exc}") from exc


def load_pdf(
    data: bytes,
    filename: str,
    *,
    ocr_enabled: bool = True,
    ocr_language: str = "eng",
    tesseract_cmd: str | None = None,
) -> ParsedDocument:
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises a variety of types
        raise PDFParseError(f"Could not open PDF: {exc}") from exc

    with pdf:
        if pdf.needs_pass:
            raise PDFParseError("This PDF is password-protected.")
        if pdf.page_count == 0:
            raise PDFParseError("This PDF has no pages.")

        raw_pages: list[tuple[list[_RawBlock], list[tuple[fitz.Rect, str]], float]] = []
        for page in pdf:
            tables = _extract_tables(page)
            blocks = _extract_text_blocks(page, [rect for rect, _ in tables])
            raw_pages.append((blocks, tables, float(page.rect.height)))

        body_size = _body_font_size(raw_pages)
        boilerplate = _repeated_edge_lines(raw_pages)
        ocr = _OCR(enabled=ocr_enabled, language=ocr_language, cmd=tesseract_cmd)

        pages: list[ParsedPage] = []
        section: str | None = None
        for index, page in enumerate(pdf):
            raw_blocks, tables, height = raw_pages[index]
            parsed = ParsedPage(number=index + 1)
            section = _build_page_blocks(parsed, raw_blocks, tables, body_size, boilerplate, height, section)

            if parsed.word_count < _OCR_MIN_WORDS and _has_images(page):
                ocr_text = ocr.run(page)
                if ocr_text and len(ocr_text.split()) > parsed.word_count:
                    parsed.blocks = [
                        Block(text=p, page=parsed.number, kind="text", section=section)
                        for p in _paragraphs(ocr_text)
                    ]
                    parsed.is_ocr = True
            pages.append(parsed)

    logger.info(
        "Parsed %s: %d pages, %d blocks, %d OCR pages",
        filename, len(pages), sum(len(p.blocks) for p in pages), sum(p.is_ocr for p in pages),
    )
    return ParsedDocument(filename=filename, pages=pages)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_tables(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    try:
        found = page.find_tables()
    except Exception as exc:  # older PyMuPDF or odd pages
        logger.debug("Table detection failed on page %d: %s", page.number + 1, exc)
        return []
    tables: list[tuple[fitz.Rect, str]] = []
    for table in found.tables:
        try:
            rows = table.extract()
        except Exception:
            continue
        markdown = _rows_to_markdown(rows)
        if markdown:
            tables.append((fitz.Rect(table.bbox), markdown))
    return tables


def _rows_to_markdown(rows: list[list[str | None]]) -> str:
    cleaned = [[(c or "").replace("\n", " ").replace("|", "/").strip() for c in row] for row in rows]
    cleaned = [r for r in cleaned if any(r)]
    if len(cleaned) < 2 or max(len(r) for r in cleaned) < 2:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    header, *body = cleaned
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def _extract_text_blocks(page: fitz.Page, table_rects: list[fitz.Rect]) -> list[_RawBlock]:
    data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)
    blocks: list[_RawBlock] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        rect = fitz.Rect(block["bbox"])
        if any(_overlap_ratio(rect, t) > 0.5 for t in table_rects):
            continue  # this text already lives in a table chunk
        lines: list[_Line] = []
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            text = re.sub(r"\s+", " ", text)
            size = max(s["size"] for s in spans)
            bold = all((s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in spans)
            lines.append(_Line(text=text, size=round(size, 1), bold=bold))
        if lines:
            blocks.append(_RawBlock(lines=lines, bbox=tuple(rect)))
    return blocks


def _overlap_ratio(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = fitz.Rect(a) & b
    if inter.is_empty or a.get_area() == 0:
        return 0.0
    return inter.get_area() / a.get_area()


def _body_font_size(raw_pages: list[tuple[list[_RawBlock], list, float]]) -> float:
    counter: Counter[float] = Counter()
    for blocks, _, _ in raw_pages:
        for block in blocks:
            for line in block.lines:
                counter[line.size] += len(line.text)
    return counter.most_common(1)[0][0] if counter else 11.0


_Y_BUCKET = 12.0  # points; lines of a running header/footer sit at the same height on every page
# Page counters that change on every page: "3/5", "Page 3 of 10", "page 3", or a bare "7".
_PAGE_COUNTER = re.compile(r"(?:\bpage\s*)?\b\d+\s*(?:/|of)\s*\d+\b|\bpage\s*\d+\b|^\s*-?\s*\d+\s*-?\s*$", re.I)
_MARGIN = 0.12  # share of the page height counted as top/bottom margin
EdgeKey = tuple[str, int]


def _edge_keys(text: str, block: _RawBlock, page_height: float) -> list[EdgeKey]:
    """Keys under which an edge line is counted: its exact text at its height, plus, for lines in
    the page margins, digit-normalized text so "Page 3 of 10" matches "Page 4 of 10"."""
    y0, y1 = block.bbox[1], block.bbox[3]
    if not (y0 < page_height * _MARGIN or y1 > page_height * (1 - _MARGIN)):
        return []  # body content is never treated as a running header/footer
    bucket = int(y0 // _Y_BUCKET)
    keys = [(text.strip().lower(), bucket)]
    without_counter = _PAGE_COUNTER.sub("#", text.lower()).strip()
    if without_counter != keys[0][0]:
        keys.append((without_counter, bucket))
    return keys


def _repeated_edge_lines(raw_pages: list[tuple[list[_RawBlock], list, float]]) -> set[EdgeKey]:
    """Headers/footers: lines near the top/bottom of a page, at the same height, repeated on
    at least half of the pages."""
    if len(raw_pages) < 3:
        return set()
    counter: Counter[EdgeKey] = Counter()
    for blocks, _, height in raw_pages:
        lines = [(line.text, block) for block in blocks for line in block.lines]
        if not lines:
            continue
        edges = lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]
        keys = {k for text, block in edges for k in _edge_keys(text, block, height)}
        counter.update(k for k in keys if k[0] and len(k[0]) < 120)
    threshold = len(raw_pages) * 0.5
    return {key for key, n in counter.items() if n >= threshold}


def _is_boilerplate(line: _Line, block: _RawBlock, boilerplate: set[EdgeKey], page_height: float) -> bool:
    return bool(boilerplate) and any(k in boilerplate for k in _edge_keys(line.text, block, page_height))


def _is_heading(line: _Line, block: _RawBlock, body_size: float) -> bool:
    text = line.text
    words = text.split()
    if not 2 <= len(text) <= 120 or len(words) > 14:
        return False
    if _ONLY_NUMBERS_OR_PUNCT.match(text) or text.endswith((".", ",", ";")) or "|" in text:
        # "|" means a table header row drawn as text, not a section title.
        return False
    if line.size >= body_size * 1.15:
        return True
    short_block = len(block.lines) <= 2
    if _NUMBERED_HEADING.match(text) and (line.bold or line.size > body_size) and short_block:
        return True
    if _LABEL_VALUE.match(text):
        return False  # bold "Label: value" lines are form fields / totals, not headings
    if line.bold and line.size >= body_size * 0.95 and short_block:
        return True
    return short_block and len(words) >= 2 and text.isupper() and len(text) <= 60


def _join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith("-") and line[:1].islower():
            out = out[:-1] + line  # de-hyphenate words broken across lines
        elif re.match(r"^([•\-\*▪◦●–]|\d+[\.\)])\s", line):
            out += "\n" + line  # keep list items on their own line
        else:
            out += " " + line
    return out.strip()


def _build_page_blocks(
    parsed: ParsedPage,
    raw_blocks: list[_RawBlock],
    tables: list[tuple[fitz.Rect, str]],
    body_size: float,
    boilerplate: set[EdgeKey],
    page_height: float,
    section: str | None,
) -> str | None:
    """Turn raw lines into heading/text/table blocks in reading order. Returns the running section."""
    items: list[tuple[float, str, object]] = [(b.bbox[1], "text", b) for b in raw_blocks]
    items += [(rect.y0, "table", md) for rect, md in tables]
    items.sort(key=lambda item: item[0])  # stable: keeps PDF order for equal positions

    for _, kind, payload in items:
        if kind == "table":
            parsed.blocks.append(Block(text=str(payload), page=parsed.number, kind="table", section=section))
            continue
        block: _RawBlock = payload  # type: ignore[assignment]
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                text = _join_lines(buffer)
                if text:
                    parsed.blocks.append(Block(text=text, page=parsed.number, kind="text", section=section))
                buffer.clear()

        for line in block.lines:
            if _is_boilerplate(line, block, boilerplate, page_height):
                continue
            if _is_heading(line, block, body_size):
                flush()
                section = line.text
                parsed.blocks.append(Block(text=line.text, page=parsed.number, kind="heading", section=section))
            else:
                buffer.append(line.text)
        flush()
    return section


def _has_images(page: fitz.Page) -> bool:
    try:
        return bool(page.get_images(full=False))
    except Exception:
        return False


def _paragraphs(text: str) -> list[str]:
    parts = [re.sub(r"[ \t]*\n[ \t]*", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in parts if len(p) > 1]


class _OCR:
    """Lazy pytesseract wrapper that disables itself if Tesseract is unavailable."""

    def __init__(self, *, enabled: bool, language: str, cmd: str | None = None) -> None:
        self.enabled = enabled
        self.language = language
        self.cmd = cmd

    def run(self, page: fitz.Page) -> str:
        if not self.enabled:
            return ""
        try:
            import pytesseract
            from PIL import Image

            if self.cmd:
                pytesseract.pytesseract.tesseract_cmd = self.cmd

            pix = page.get_pixmap(dpi=300)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            return pytesseract.image_to_string(image, lang=self.language)
        except Exception as exc:  # TesseractNotFoundError, missing language pack, ...
            logger.warning("OCR unavailable, skipping scanned pages: %s", exc)
            self.enabled = False
            return ""
