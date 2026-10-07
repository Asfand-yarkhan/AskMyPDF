"""Grounded QA / EXPLAIN: history-aware rewrite -> hybrid retrieval -> cited, streamed answer.

Works on one document or several at once (citations then name the document: [Doc 2, p. 4]).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Literal

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.chains.common import (
    Event, cite_tag, format_context, history_messages, language_instruction, status, to_sources, token,
)
from app.config import Settings
from app.ingestion.loader import load_pdf
from app.llm import get_chat_model
from app.retrieval import HybridRetriever
from app.schemas import ChatTurn, DocumentInfo

logger = logging.getLogger(__name__)

REWRITE_SYSTEM = """Rewrite the user's latest message as a standalone search query for retrieving passages \
from a document. Resolve pronouns and references using the chat history and keep key terms, codes and \
names exactly. Keep the user's language; if it is not English, append " | " and an English translation. \
Do NOT answer it. Output only the query."""

_rewrite_prompt = ChatPromptTemplate.from_messages(
    [("system", REWRITE_SYSTEM), MessagesPlaceholder("history"), ("human", "{question}")]
)

GROUNDING_RULES = """Rules:
1. Use ONLY the document excerpts below. Never use outside knowledge and never guess.
2. Cite every factual statement with the excerpt's tag, copied exactly, e.g. {cite_example}. Use only \
tags that appear in the excerpts.
3. If the excerpts do not contain the answer, reply with exactly: "{not_found}" and nothing else.
4. Copy numbers, names, dates and quoted terms exactly as written.
5. Excerpts are in document order and page tags show where each page starts. A value printed \
after a table or section (totals, status, CGPA, subtotal...) belongs to the table or section ABOVE it, \
never to the heading that follows it.
6. For "last", "latest", "most recent", "first", "highest", "total" or "list every" questions, walk \
through the excerpts from top to bottom and pair each label (date, semester, version, name) with the \
values that follow it until the next label starts, then answer from those pairs. Do not skip entries.
7. {language}
8. Format with Markdown: short paragraphs, bullet lists for multiple items, tables for comparisons."""

QA_SYSTEM = (
    "You are AskMyPDF, a precise assistant that answers questions about a document.\n\n"
    + GROUNDING_RULES
    + "\n9. Be concise: answer directly first, then add supporting detail.\n\nDocument excerpts:\n{context}"
)

EXPLAIN_SYSTEM = (
    "You are AskMyPDF, a patient teacher explaining concepts from a document.\n\n"
    + GROUNDING_RULES
    + "\n9. Explain step by step in simple words: start with a one-line intuition, then break the concept "
    "into parts, then summarize. You may add a short analogy to aid understanding, but label it "
    "'Analogy:' and do not introduce new facts.\n\nDocument excerpts:\n{context}"
)


def _answer_prompt(mode: Literal["qa", "explain"]) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", EXPLAIN_SYSTEM if mode == "explain" else QA_SYSTEM),
            MessagesPlaceholder("history"),
            ("human", "{question}"),
        ]
    )


async def rewrite_query(question: str, history: list[ChatTurn], language: str, settings: Settings) -> str:
    """Standalone English query; skipped when there is nothing to resolve."""
    if not history and language == "english":
        return question
    chain = _rewrite_prompt | get_chat_model(0.0, "router") | StrOutputParser()
    try:
        rewritten = (await chain.ainvoke({
            "history": history_messages(history, settings.max_history_turns),
            "question": question,
        })).strip().strip('"')
    except Exception as exc:
        logger.warning("Query rewrite failed, using original question: %s", exc)
        return question
    return rewritten if 3 <= len(rewritten) <= 500 else question


def page_documents(info: DocumentInfo, settings: Settings) -> list[Document]:
    """One Document per PDF page (headers/footers removed), for whole-document answers."""
    path: Path = settings.upload_dir / f"{info.doc_id}.pdf"
    if not path.exists():
        return []
    parsed = load_pdf(
        path.read_bytes(), info.filename, ocr_enabled=settings.ocr_enabled,
        ocr_language=settings.ocr_language, tesseract_cmd=settings.tesseract_cmd,
    )
    return [
        Document(
            page_content=page.text,
            metadata={
                "chunk_id": f"{info.doc_id}-page-{page.number}", "chunk_index": page.number - 1,
                "page": page.number, "page_end": page.number, "kind": "page",
                "has_table": page.table_count > 0, "doc_id": info.doc_id, "filename": info.filename,
                "section": next((b.section for b in page.blocks if b.section), ""),
            },
        )
        for page in parsed.pages
        if page.text.strip()
    ]


def format_pages(pages: Sequence[Document], doc_numbers: dict[str, int] | None = None) -> str:
    """Whole documents as continuous text with a tag at every page start."""
    parts = []
    current_doc = None
    for d in pages:
        number = (doc_numbers or {}).get(str(d.metadata.get("doc_id")))
        if number and d.metadata.get("doc_id") != current_doc:
            current_doc = d.metadata.get("doc_id")
            parts.append(f"===== Doc {number}: {d.metadata.get('filename', '')} =====")
        parts.append(f"{cite_tag(d.metadata['page'], number)}\n{d.page_content}")
    return "\n\n".join(parts)


async def stream_answer(
    *,
    docs: Sequence[DocumentInfo],
    question: str,
    history: list[ChatTurn],
    language: str,
    settings: Settings,
    retriever: HybridRetriever,
    mode: Literal["qa", "explain"] = "qa",
    topic: str | None = None,
) -> AsyncIterator[Event]:
    multi = len(docs) > 1
    doc_numbers = {d.doc_id: i for i, d in enumerate(docs, start=1)} if multi else None
    total_chars = sum(d.total_chars for d in docs)
    passages: list[Document] = []
    whole = 0 < total_chars <= settings.full_context_max_chars and all(d.total_chars for d in docs)
    if whole:
        # Small documents: give the model every page in order (no chunk overlaps or separators),
        # which beats top-k retrieval for "last", "total" and "compare" questions.
        yield status("Reading the whole document..." if not multi else f"Reading all {len(docs)} documents...")
        for info in docs:
            passages += await asyncio.to_thread(page_documents, info, settings)
    if not passages:
        whole = False
        if history:
            yield status("Understanding your question...")
        query = await rewrite_query(topic or question, history, language, settings)
        yield status("Searching the document..." if not multi else f"Searching {len(docs)} documents...")
        passages = await asyncio.to_thread(
            retriever.search,
            [d.doc_id for d in docs],
            query,
            k=settings.retrieval_k + (2 if mode == "explain" else 0) + (2 if multi else 0),
        )
        # Reading order (per document) helps the model follow tables and sections.
        order = {d.doc_id: i for i, d in enumerate(docs)}
        passages.sort(key=lambda p: (order.get(str(p.metadata.get("doc_id")), 0), int(p.metadata.get("chunk_index", 0))))
    yield {"type": "sources", "sources": to_sources(passages)}
    if not passages:
        yield token(settings.not_found_message)
        return

    context = format_pages(passages, doc_numbers) if whole else format_context(passages, doc_numbers)
    chain = _answer_prompt(mode) | get_chat_model(settings.qa_temperature) | StrOutputParser()
    async for piece in chain.astream({
        "context": context,
        "history": history_messages(history, settings.max_history_turns),
        "question": question,
        "not_found": settings.not_found_message,
        "language": language_instruction(language),
        "cite_example": "[Doc 1, p. 4]" if multi else "[p. 4]",
    }):
        if piece:
            yield token(piece)
