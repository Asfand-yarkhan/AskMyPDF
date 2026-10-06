"""Grounded QA / EXPLAIN: history-aware rewrite -> MMR retrieval -> cited, streamed answer."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Literal

from pathlib import Path

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.chains.common import (
    Event, format_context, history_messages, language_instruction, status, to_sources, token,
)
from app.config import Settings
from app.ingestion.loader import load_pdf
from app.llm import get_chat_model
from app.schemas import ChatTurn
from app.vectorstore import VectorStoreManager

logger = logging.getLogger(__name__)

REWRITE_SYSTEM = """Rewrite the user's latest message as a standalone search query for retrieving passages \
from a document. Resolve pronouns and references using the chat history. Write the query in English \
(translate Urdu / Roman Urdu if needed) and keep key terms. Do NOT answer it. Output only the query."""

_rewrite_prompt = ChatPromptTemplate.from_messages(
    [("system", REWRITE_SYSTEM), MessagesPlaceholder("history"), ("human", "{question}")]
)

GROUNDING_RULES = """Rules:
1. Use ONLY the document excerpts below. Never use outside knowledge and never guess.
2. Cite the page for every factual statement using the excerpt's tag, e.g. [p. 4]. Use only page numbers \
that appear in the excerpt headers.
3. If the excerpts do not contain the answer, reply with exactly: "{not_found}" and nothing else.
4. Copy numbers, names, dates and quoted terms exactly as written.
5. Excerpts are in document order and [p. X] markers show where each page starts. A value printed \
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


def page_documents(path: Path, settings: Settings) -> list[Document]:
    """One Document per PDF page (headers/footers removed), for whole-document answers."""
    if not path.exists():
        return []
    parsed = load_pdf(
        path.read_bytes(), path.name, ocr_enabled=settings.ocr_enabled,
        ocr_language=settings.ocr_language, tesseract_cmd=settings.tesseract_cmd,
    )
    return [
        Document(
            page_content=page.text,
            metadata={
                "chunk_id": f"page-{page.number}", "chunk_index": page.number - 1, "page": page.number,
                "page_end": page.number, "kind": "page", "has_table": page.table_count > 0,
                "section": next((b.section for b in page.blocks if b.section), ""),
            },
        )
        for page in parsed.pages
        if page.text.strip()
    ]


def format_pages(pages: list[Document]) -> str:
    """The whole document as continuous text with a marker at every page start."""
    return "\n\n".join(f"[p. {d.metadata['page']}]\n{d.page_content}" for d in pages)


async def stream_answer(
    *,
    doc_id: str,
    question: str,
    history: list[ChatTurn],
    language: str,
    settings: Settings,
    vectorstore: VectorStoreManager,
    mode: Literal["qa", "explain"] = "qa",
    topic: str | None = None,
    full_context: bool = False,
) -> AsyncIterator[Event]:
    docs: list[Document] = []
    if full_context:
        # Small document: give the model every page in order (no chunk overlaps or separators),
        # which beats top-k retrieval for "last", "total" and "compare" questions.
        yield status("Reading the whole document...")
        docs = await asyncio.to_thread(page_documents, settings.upload_dir / f"{doc_id}.pdf", settings)
    if not docs:
        if history:
            yield status("Understanding your question...")
        query = await rewrite_query(topic or question, history, language, settings)
        yield status("Searching the document...")
        docs = await asyncio.to_thread(
            vectorstore.mmr_search,
            doc_id,
            query,
            k=settings.retrieval_k + (2 if mode == "explain" else 0),
            fetch_k=settings.retrieval_fetch_k,
            lambda_mult=settings.mmr_lambda,
        )
        docs.sort(key=lambda d: int(d.metadata.get("chunk_index", 0)))  # reading order helps the model
    yield {"type": "sources", "sources": to_sources(docs)}
    if not docs:
        yield token(settings.not_found_message)
        return

    context = format_pages(docs) if full_context and docs[0].metadata.get("kind") == "page" else format_context(docs)
    chain = _answer_prompt(mode) | get_chat_model(settings.qa_temperature) | StrOutputParser()
    async for piece in chain.astream({
        "context": context,
        "history": history_messages(history, settings.max_history_turns),
        "question": question,
        "not_found": settings.not_found_message,
        "language": language_instruction(language),
    }):
        if piece:
            yield token(piece)
