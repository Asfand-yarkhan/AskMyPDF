"""Map-reduce summaries and study notes over the whole document (or a topic slice)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Literal

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.chains.common import (
    Event, evenly_sample, language_instruction, status, to_sources, token, with_page_markers,
)
from app.config import Settings
from app.llm import get_chat_model
from app.retrieval import HybridRetriever

logger = logging.getLogger(__name__)

Mode = Literal["short", "detailed", "bullet", "notes"]

REDUCE_LIMIT_CHARS = 24_000
PARAGRAPH = "\n\n"

MAP_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You condense excerpts of a document. Keep every important fact, definition, number, name and "
     "conclusion. Do not add anything that is not in the text. After each fact keep its page tag exactly "
     "as given, e.g. [p. 7]. Write in English. Output a compact bullet list."),
    ("human", "Excerpts:\n\n{text}"),
])

COMBINE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Merge these partial summaries into one compact bullet list without losing distinct facts. "
     "Keep the [p. X] page tags. Do not add new information."),
    ("human", "{text}"),
])

STYLE_INSTRUCTIONS: dict[str, str] = {
    "short": "Write a concise summary of one short paragraph (about 80-120 words) capturing the core idea.",
    "detailed": (
        "Write a detailed, well-structured summary (about 400-700 words): a one-paragraph overview, then "
        "Markdown sections (###) following the document's structure, then a short 'Conclusion'."
    ),
    "bullet": (
        "List the 8-15 most important key points as Markdown bullets, ordered as they appear in the "
        "document. Bold the key term in each bullet."
    ),
    "notes": (
        "Create well-organized study notes in Markdown: ### headings per major topic, bullet points, "
        "**bold** key terms with one-line definitions, important numbers/formulas, and finish with a "
        "'Quick revision' checklist of 5-8 items."
    ),
}

REDUCE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are AskMyPDF. Using ONLY the material below (condensed from the document '{filename}'), "
     "complete the task. Do not add outside knowledge. Keep page citations in the form [p. X] after "
     "the facts they support; use only page tags that appear in the material.\n\n"
     "Task: {style}\n{focus}\n{language}"),
    ("human", "Material:\n\n{text}"),
])


def _tagged(doc: Document) -> str:
    return f"[p. {int(doc.metadata.get('page', 1))}] {with_page_markers(doc)}"


def group_texts(texts: Sequence[str], target: int) -> list[str]:
    """Pack texts into groups of about `target` chars, one map call each."""
    groups: list[str] = []
    current: list[str] = []
    size = 0
    for text in texts:
        if current and size + len(text) > target:
            groups.append(PARAGRAPH.join(current))
            current, size = [], 0
        current.append(text)
        size += len(text) + 2
    if current:
        groups.append(PARAGRAPH.join(current))
    return groups


def select_within_budget(docs: Sequence[Document], budget: int) -> list[Document]:
    """Chunks to summarize when the whole document exceeds the token budget.

    Takes the opening chunk of every section first (so every topic is represented),
    then fills the rest evenly across the document. Returns chunks in reading order.
    """
    if sum(len(d.page_content) for d in docs) <= budget:
        return list(docs)
    chosen: dict[int, Document] = {}
    used = 0

    def take(doc: Document) -> bool:
        nonlocal used
        idx = int(doc.metadata.get("chunk_index", 0))
        if idx in chosen or used + len(doc.page_content) > budget:
            return False
        chosen[idx] = doc
        used += len(doc.page_content)
        return True

    seen_sections: set[str] = set()
    for doc in docs:  # section openers, capped at half the budget
        section = str(doc.metadata.get("section") or "")
        if section and section not in seen_sections and used < budget // 2:
            seen_sections.add(section)
            take(doc)
    remaining = [d for d in docs if int(d.metadata.get("chunk_index", 0)) not in chosen]
    avg = max(sum(len(d.page_content) for d in remaining) // max(len(remaining), 1), 1)
    for doc in evenly_sample(remaining, max((budget - used) // avg, 1)):
        take(doc)
    return [chosen[i] for i in sorted(chosen)]


async def _collapse(texts: list[str]) -> str:
    """Repeatedly merge partial summaries until they fit into one reduce call."""
    chain = COMBINE_PROMPT | get_chat_model(0.0, "router") | StrOutputParser()
    while sum(len(t) for t in texts) > REDUCE_LIMIT_CHARS and len(texts) > 1:
        batches = group_texts(texts, REDUCE_LIMIT_CHARS)
        if len(batches) == len(texts):  # cannot pack further; pair them up
            batches = [PARAGRAPH.join(texts[i : i + 2]) for i in range(0, len(texts), 2)]
        texts = await chain.abatch([{"text": b} for b in batches], config={"max_concurrency": 1})
    return PARAGRAPH.join(texts)


async def stream_summary(
    *,
    doc_id: str,
    filename: str,
    mode: Mode,
    topic: str | None,
    language: str,
    settings: Settings,
    retriever: HybridRetriever,
) -> AsyncIterator[Event]:
    if topic:
        yield status(f"Finding passages about '{topic}'...")
        docs = await asyncio.to_thread(retriever.search, [doc_id], topic, k=12)
        docs.sort(key=lambda d: int(d.metadata.get("chunk_index", 0)))
    else:
        yield status("Reading the whole document...")
        docs = await asyncio.to_thread(retriever.vectorstore.all_chunks, doc_id)

    if not docs:
        yield token(settings.not_found_message)
        return

    total = sum(len(d.page_content) for d in docs)
    selected = select_within_budget(docs, settings.summary_max_input_chars)
    # Sources power the citation hover previews in the UI.
    yield {"type": "sources", "sources": to_sources(selected)}
    if len(selected) < len(docs):
        share = sum(len(d.page_content) for d in selected) / total
        logger.info("Summary of %s uses %d/%d chunks (%.0f%% of text)", doc_id, len(selected), len(docs), share * 100)
        yield status(f"Long document: focusing on every section's key passages ({share:.0%} of the text)...")

    groups = group_texts([_tagged(d) for d in selected], settings.summary_group_chars)
    if len(groups) == 1:
        material = groups[0]
    else:
        # Map on the small model: it has its own rate-limit quota and is fast. Sequential calls
        # let the SDK pace itself against per-minute token limits.
        map_chain = MAP_PROMPT | get_chat_model(0.0, "router") | StrOutputParser()
        partials: list[str] = []
        for i, group in enumerate(groups, start=1):
            yield status(f"Reading part {i}/{len(groups)}...")
            partials.append(await map_chain.ainvoke({"text": group}))
        yield status("Combining the parts...")
        material = await _collapse(partials)

    yield status("Writing the summary...")
    focus = f"Focus only on: {topic}." if topic else "Cover the whole document."
    reduce_chain = REDUCE_PROMPT | get_chat_model(settings.qa_temperature, "main", "low") | StrOutputParser()
    async for piece in reduce_chain.astream({
        "filename": filename,
        "style": STYLE_INSTRUCTIONS[mode],
        "focus": focus,
        "language": language_instruction(language),
        "text": material,
    }):
        if piece:
            yield token(piece)
