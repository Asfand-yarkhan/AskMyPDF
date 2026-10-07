"""Structure-aware chunking: sections -> paragraphs -> sentences -> characters.

Headings are separated by a triple newline so the recursive splitter first tries to
cut at section boundaries, then paragraphs, then lines, then sentence ends, and only
as a last resort inside a sentence.

Tables that fit in a chunk are kept inline as one atomic unit together with the short
"totals" lines that follow them (e.g. "CGPA: 3.5"), so a caption, its table and its
totals never end up in different chunks. Oversized tables become standalone chunks
split by rows with the header repeated.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ingestion.loader import Block, ParsedDocument
from app.schemas import ChunkConfig

SECTION_BREAK = "\n\n\n"
SEPARATORS: list[str] = [
    SECTION_BREAK,  # heading boundaries
    "\n\n",  # paragraphs
    "\n",  # lines / list items
    ". ", "? ", "! ", "۔ ",  # sentence ends (incl. Urdu full stop)
    "; ", ": ", ", ",  # clauses
    " ",  # words
    "",  # characters
]
# Newlines inside atomic units are swapped for this private-use character while splitting,
# so no separator can match inside a table; they are restored in the final chunk text.
ATOMIC_NEWLINE = ""
MAX_TABLE_CHARS = 4000  # standalone table chunk; larger tables are split by rows with header repeated
MAX_TOTALS_LINES = 3  # short "Label: value" lines after a table that are kept with it
MAX_TOTALS_CHARS = 80
MIN_CHUNK_CHARS = 3
MIN_CARRY_CHARS = 120  # trailing short lines of a chunk repeated at the start of the next one
MAX_CARRY_LINE = 100  # lines longer than this are prose and are not carried
# "Semester: Fall 2024", "Invoice No: 42", "Patient : Ali" - a short label opening a record.
_RECORD_LABEL = re.compile(r"^[^\W\d_][\w .()/&-]{0,40}?\s*:\s*\S.{0,60}$")


@dataclass
class Chunk:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Piece:
    text: str
    page: int
    page_end: int
    section: str | None
    kind: str
    page_breaks: str = ""  # "offset:page;offset:page" for pages that start inside the piece
    has_table: bool = False


@dataclass
class _Flow:
    """Running text buffer with offset -> (page, section) markers for citation mapping."""

    parts: list[str] = field(default_factory=list)
    length: int = 0
    offsets: list[int] = field(default_factory=list)
    marks: list[tuple[int, str | None]] = field(default_factory=list)
    table_spans: list[tuple[int, int]] = field(default_factory=list)

    def add(self, text: str, page: int, section: str | None, *, sep: str = "\n\n", table: bool = False) -> None:
        if self.parts:
            self.parts.append(sep)
            self.length += len(sep)
        self.offsets.append(self.length)
        self.marks.append((page, section))
        if table:
            self.table_spans.append((self.length, self.length + len(text)))
        self.parts.append(text)
        self.length += len(text)

    def at(self, offset: int) -> tuple[int, str | None]:
        idx = max(bisect.bisect_right(self.offsets, max(offset, 0)) - 1, 0)
        return self.marks[idx]

    def page_breaks(self, start: int, end: int) -> str:
        """Pages that begin strictly inside [start, end], as offsets relative to start."""
        breaks: list[str] = []
        page = self.at(start)[0]
        lo = bisect.bisect_right(self.offsets, start)
        for i in range(lo, len(self.offsets)):
            offset = self.offsets[i]
            if offset > end:
                break
            if self.marks[i][0] != page:
                page = self.marks[i][0]
                breaks.append(f"{offset - start}:{page}")
        return ";".join(breaks)

    def has_table(self, start: int, end: int) -> bool:
        return any(s < end and e > start for s, e in self.table_spans)

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def __bool__(self) -> bool:
        return bool(self.parts)


def make_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=SEPARATORS,
        keep_separator="end",  # sentence punctuation stays with its sentence
        add_start_index=True,
        strip_whitespace=True,
    )


def chunk_document(doc: ParsedDocument, config: ChunkConfig, doc_id: str) -> list[Chunk]:
    if config.strategy == "slides":
        pieces = _chunk_slides(doc, config)
    else:
        pieces = _chunk_flow(doc, config)

    chunks: list[Chunk] = []
    for piece in pieces:
        text = piece.text.replace(ATOMIC_NEWLINE, "\n").strip()
        if len(text) < MIN_CHUNK_CHARS:
            continue
        index = len(chunks)
        chunks.append(
            Chunk(
                text=text,
                metadata={
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}-{index:05d}",
                    "chunk_index": index,
                    "page": piece.page,
                    "page_end": max(piece.page_end, piece.page),
                    "page_breaks": piece.page_breaks,
                    "section": piece.section or "",  # Chroma metadata cannot be None
                    "kind": piece.kind,
                    "has_table": piece.has_table or piece.kind == "table",
                    "filename": doc.filename,
                    "char_count": len(text),
                },
            )
        )
    return chunks


def _is_totals_line(block: Block) -> bool:
    text = block.text.strip()
    return block.kind == "text" and len(text) <= MAX_TOTALS_CHARS and "\n" not in text and ":" in text


def _chunk_flow(doc: ParsedDocument, config: ChunkConfig) -> list[_Piece]:
    splitter = make_splitter(config.chunk_size, config.chunk_overlap)
    inline_limit = int(config.chunk_size * 0.85)
    pieces: list[_Piece] = []
    flow = _Flow()
    blocks = doc.blocks
    i = 0

    def flush() -> None:
        nonlocal flow
        if flow:
            pieces.extend(_split_flow(flow, splitter, config.chunk_overlap))
        flow = _Flow()

    while i < len(blocks):
        block = blocks[i]
        if block.kind == "heading":
            flow.add(block.text, block.page, block.section, sep=SECTION_BREAK)
        elif block.kind == "table" and len(block.text) <= inline_limit:
            flow.add(block.text.replace("\n", ATOMIC_NEWLINE), block.page, block.section, table=True)
            # Totals right below a table ("CGPA: 3.5", "Total: 120") belong to that table.
            absorbed = 0
            while (
                absorbed < MAX_TOTALS_LINES
                and i + 1 < len(blocks)
                and _is_totals_line(blocks[i + 1])
            ):
                i += 1
                absorbed += 1
                flow.add(blocks[i].text, blocks[i].page, blocks[i].section, sep=ATOMIC_NEWLINE)
        elif block.kind == "table":
            flush()  # oversized table: keep document order, emit standalone
            pieces.extend(_table_pieces(block))
        else:
            flow.add(block.text, block.page, block.section)
        i += 1
    flush()
    return pieces


def _split_flow(flow: _Flow, splitter: RecursiveCharacterTextSplitter, carry_chars: int) -> list[_Piece]:
    text = flow.text
    pieces: list[_Piece] = []
    for part in splitter.create_documents([text]):
        start = part.metadata.get("start_index", -1)
        if start is None or start < 0:
            start = text.find(part.page_content[:50])
        end = start + len(part.page_content) - 1
        page, section = flow.at(start)
        page_end, _ = flow.at(end)
        pieces.append(
            _Piece(
                part.page_content, page, page_end, section, "text",
                page_breaks=flow.page_breaks(start, end),
                has_table=flow.has_table(start, end),
            )
        )
    return _carry_tail_lines(pieces, max(carry_chars, MIN_CARRY_CHARS))


def _short_tail(text: str, budget: int) -> str:
    """Trailing short lines of a chunk (labels, list items, table rows) within `budget` chars.

    The splitter's own overlap works on whole splits, so when it cuts between sections nothing
    is carried over. For structured content that loses the lead-in: a chunk that starts with a
    semester's grades but not its "Semester: Fall 2024" line is ambiguous. Long prose lines stop
    the scan, since sentences are already split with overlap.
    """
    lines = [ln.strip() for ln in text.replace(ATOMIC_NEWLINE, "\n").splitlines() if ln.strip()]
    tail: list[str] = []
    used = 0
    for line in reversed(lines[1:]):  # never carry a chunk's entire content
        if len(line) > MAX_CARRY_LINE or used + len(line) > budget:
            break
        tail.insert(0, line)
        used += len(line) + 2
    return "\n\n".join(tail)


def _open_record_header(text: str) -> str | None:
    """The "Label: value" line that opens the record a chunk ends inside.

    Scanning backwards, the first label line that is followed by at least one plain line is the
    header of the still-open record ("Semester: Spring 2025" followed by course rows). A label
    with nothing after it is a trailing total ("CGPA : 3.39") and does not count.
    """
    lines = [ln.strip() for ln in text.replace(ATOMIC_NEWLINE, "\n").splitlines() if ln.strip()]
    seen_plain = False
    for line in reversed(lines):
        if _RECORD_LABEL.match(line):
            return line if seen_plain else None
        seen_plain = True
    return None


def _carry_tail_lines(pieces: list[_Piece], budget: int) -> list[_Piece]:
    for prev, cur in zip(pieces, pieces[1:]):
        if prev.kind == "table" or cur.kind == "table":
            continue
        start = cur.text.lstrip()
        tail = _short_tail(prev.text, budget)
        tail_needed = bool(tail) and not start.startswith(tail[:40])
        header = _open_record_header(prev.text)
        header_needed = (
            bool(header) and not start.startswith(header) and not (tail_needed and header in tail)
        )
        parts = ([header] if header_needed else []) + ([tail] if tail_needed else [])
        if parts:
            prefix = "\n\n".join(parts) + "\n\n"
            cur.text = prefix + cur.text
            if cur.page_breaks:  # keep page-break offsets pointing at the same text
                cur.page_breaks = ";".join(
                    f"{int(off) + len(prefix)}:{page}"
                    for off, _, page in (entry.partition(":") for entry in cur.page_breaks.split(";"))
                )
    return pieces


def _table_pieces(block: Block) -> list[_Piece]:
    if len(block.text) <= MAX_TABLE_CHARS:
        return [_Piece(block.text, block.page, block.page, block.section, "table")]
    lines = block.text.splitlines()
    header, rows = lines[:2], lines[2:]
    pieces: list[_Piece] = []
    current: list[str] = []
    size = sum(len(h) for h in header)
    for row in rows:
        if current and size + len(row) > MAX_TABLE_CHARS:
            pieces.append(_Piece("\n".join(header + current), block.page, block.page, block.section, "table"))
            current, size = [], sum(len(h) for h in header)
        current.append(row)
        size += len(row) + 1
    if current:
        pieces.append(_Piece("\n".join(header + current), block.page, block.page, block.section, "table"))
    return pieces


def _chunk_slides(doc: ParsedDocument, config: ChunkConfig) -> list[_Piece]:
    fallback = make_splitter(1000, 150)
    pieces: list[_Piece] = []
    for page in doc.pages:
        if not page.blocks:
            continue
        title = next((b.text for b in page.blocks if b.kind == "heading"), None)
        section = title or page.blocks[0].section
        text = page.text.strip()
        has_table = page.table_count > 0
        if len(text) <= config.chunk_size:
            pieces.append(_Piece(text, page.number, page.number, section, "slide", has_table=has_table))
        else:
            for part in fallback.split_text(text):
                pieces.append(_Piece(part, page.number, page.number, section, "slide", has_table=has_table))
    return pieces
