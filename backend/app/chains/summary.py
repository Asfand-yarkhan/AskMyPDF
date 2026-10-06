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
from app.vectorstore import VectorStoreManager

logger = logging.getLogger(__name__)

Mode = Literal["short", "detailed", "bullet", "notes"]

MIN_GROUP_CHARS = 6_000
MAX_GROUP_CHARS = 24_000
TARGET_GROUPS = 24
MAX_GROUPS = 40  # beyond this, groups are sampled evenly to bound cost
REDUCE_LIMIT_CHARS = 24_000

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


def group_texts(texts: Sequence[str], total_chars: int) -> list[str]:
    """Pack chunk texts into groups sized for one map call each."""
    target = min(max(total_chars // TARGET_GROUPS, MIN_GROUP_CHARS), MAX_GROUP_CHARS)
    groups: list[str] = []
    current: list[str] = []
    size = 0
    for text in texts:
        if current and size + len(text) > target:
            groups.append("\n\n".join(current))
            current, size = [], 0
        current.append(text)
        size += len(text) + 2
    if current:
        groups.append("\n\n".join(current))
    return groups


async def _collapse(texts: list[str]) -> str:
    """Repeatedly merge partial summaries until they fit into one reduce call."""
    chain = COMBINE_PROMPT | get_chat_model(0.0) | StrOutputParser()
    while sum(len(t) for t in texts) > REDUCE_LIMIT_CHARS and len(texts) > 1:
        batches = group_texts(texts, REDUCE_LIMIT_CHARS * 2)
        if len(batches) == len(texts):  # cannot pack further; pair them up
            batches = ["\n\n".join(texts[i : i + 2]) for i in range(0, len(texts), 2)]
        texts = await chain.abatch([{"text": b} for b in batches], config={"max_concurrency": 3})
    return "\n\n".join(texts)


async def stream_summary(
    *,
    doc_id: str,
    filename: str,
    mode: Mode,
    topic: str | None,
    language: str,
    settings: Settings,
    vectorstore: VectorStoreManager,
) -> AsyncIterator[Event]:
    if topic:
        yield status(f"Finding passages about '{topic}'...")
        docs = await asyncio.to_thread(
            vectorstore.mmr_search, doc_id, topic, k=12, fetch_k=40, lambda_mult=0.7
        )
        docs.sort(key=lambda d: int(d.metadata.get("chunk_index", 0)))
        yield {"type": "sources", "sources": to_sources(docs)}
    else:
        yield status("Reading the whole document...")
        docs = await asyncio.to_thread(vectorstore.all_chunks, doc_id)

    if not docs:
        yield token(settings.not_found_message)
        return

    texts = [_tagged(d) for d in docs]
    groups = group_texts(texts, sum(len(t) for t in texts))
    if len(groups) > MAX_GROUPS:
        logger.info("Sampling %d of %d groups for %s", MAX_GROUPS, len(groups), doc_id)
        groups = evenly_sample(groups, MAX_GROUPS)

    if len(groups) == 1:
        material = groups[0]
    else:
        map_chain = MAP_PROMPT | get_chat_model(0.0) | StrOutputParser()
        semaphore = asyncio.Semaphore(settings.map_concurrency)
        partials: list[str] = [""] * len(groups)

        async def run(i: int, text: str) -> tuple[int, str]:
            async with semaphore:
                return i, await map_chain.ainvoke({"text": text})

        tasks = [asyncio.create_task(run(i, g)) for i, g in enumerate(groups)]
        try:
            for done, future in enumerate(asyncio.as_completed(tasks), start=1):
                i, partial = await future
                partials[i] = partial
                yield status(f"Summarizing part {done}/{len(groups)}...")
        finally:
            for t in tasks:
                t.cancel()
        yield status("Combining the parts...")
        material = await _collapse(partials)

    yield status("Writing the final answer...")
    focus = f"Focus only on: {topic}." if topic else "Cover the whole document."
    reduce_chain = REDUCE_PROMPT | get_chat_model(settings.qa_temperature) | StrOutputParser()
    async for piece in reduce_chain.astream({
        "filename": filename,
        "style": STYLE_INSTRUCTIONS[mode],
        "focus": focus,
        "language": language_instruction(language),
        "text": material,
    }):
        if piece:
            yield token(piece)
