"""Helpers shared by all chains: context formatting, language, JSON parsing, sampling."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, TypeVar

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.schemas import ChatTurn, SourceChunk

T = TypeVar("T")

LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "english": "Write the response in English.",
    "urdu": "Write the response in Urdu (Urdu script). Keep technical terms from the document as-is.",
    "hinglish": (
        "Write the response in Roman Urdu / Hinglish (Urdu-Hindi in Latin script mixed with English terms), "
        "matching the user's casual style."
    ),
}


def language_instruction(language: str | None) -> str:
    return LANGUAGE_INSTRUCTIONS.get(language or "english", LANGUAGE_INSTRUCTIONS["english"])


def page_label(meta: dict[str, Any]) -> str:
    page, end = int(meta.get("page", 1)), int(meta.get("page_end", meta.get("page", 1)))
    return f"p. {page}" if end <= page else f"p. {page}-{end}"


def with_page_markers(doc: Document) -> str:
    """Chunk text with a [p. X] marker wherever a new page starts inside the chunk."""
    text = doc.page_content
    breaks = str(doc.metadata.get("page_breaks") or "")
    if not breaks:
        return text
    for entry in reversed(breaks.split(";")):
        offset, _, page = entry.partition(":")
        if offset.isdigit() and page.isdigit() and int(offset) <= len(text):
            pos = int(offset)
            text = f"{text[:pos].rstrip()}\n[p. {page}]\n{text[pos:].lstrip()}"
    return text


def format_context(docs: Sequence[Document]) -> str:
    """Excerpts with page headers; the model copies the [p. X] tag for citations."""
    blocks = []
    for doc in docs:
        meta = doc.metadata
        section = f" | section: {meta['section']}" if meta.get("section") else ""
        kind = " | table" if meta.get("has_table") or meta.get("kind") == "table" else ""
        blocks.append(f"[p. {int(meta.get('page', 1))}]{section}{kind}\n{with_page_markers(doc)}")
    return "\n\n---\n\n".join(blocks)


def to_sources(docs: Sequence[Document]) -> list[dict[str, Any]]:
    return [
        SourceChunk(
            chunk_id=str(d.metadata.get("chunk_id", "")),
            chunk_index=int(d.metadata.get("chunk_index", 0)),
            page=int(d.metadata.get("page", 1)),
            page_end=int(d.metadata.get("page_end", d.metadata.get("page", 1))),
            section=d.metadata.get("section") or None,
            kind=str(d.metadata.get("kind", "text")),
            has_table=bool(d.metadata.get("has_table", False)),
            text=d.page_content,
        ).model_dump()
        for d in docs
    ]


def history_messages(history: Sequence[ChatTurn], max_turns: int) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for turn in list(history)[-max_turns * 2 :]:
        content = turn.content[:2000]
        messages.append(HumanMessage(content) if turn.role == "user" else AIMessage(content))
    return messages


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)


def extract_json(text: str) -> Any:
    """Parse JSON from an LLM reply, tolerating code fences and surrounding prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON found in model output")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end <= start:
        raise ValueError("unterminated JSON in model output")
    return json.loads(cleaned[start : end + 1])


def evenly_sample(items: Sequence[T], n: int) -> list[T]:
    """Pick n items spread evenly across the sequence (keeps original order)."""
    if n >= len(items):
        return list(items)
    if n <= 0:
        return []
    step = len(items) / n
    return [items[int(i * step + step / 2)] for i in range(n)]


def split_evenly(items: Sequence[T], parts: int) -> list[list[T]]:
    """Split into `parts` contiguous groups of near-equal size."""
    parts = max(1, min(parts, len(items)))
    size, extra = divmod(len(items), parts)
    groups, start = [], 0
    for i in range(parts):
        end = start + size + (1 if i < extra else 0)
        groups.append(list(items[start:end]))
        start = end
    return groups


def substantive(docs: Sequence[Document], min_chars: int = 200) -> list[Document]:
    """Prefer chunks with real content; fall back to all if too few qualify."""
    good = [d for d in docs if len(d.page_content) >= min_chars]
    return good if len(good) >= max(3, len(docs) // 3) else list(docs)


Event = dict[str, Any]


def status(message: str) -> Event:
    return {"type": "status", "message": message}


def token(content: str) -> Event:
    return {"type": "token", "content": content}
