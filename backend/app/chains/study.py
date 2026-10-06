"""Flashcard generation (grounded, validated JSON). Notes reuse the summary map-reduce."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncIterator, Sequence

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.chains.common import Event, extract_json, format_context, language_instruction, split_evenly, status
from app.chains.quiz import select_chunks
from app.config import Settings
from app.llm import get_chat_model
from app.schemas import Flashcard, FlashcardDeck
from app.vectorstore import VectorStoreManager

logger = logging.getLogger(__name__)

DEFAULT_CARDS = 12
MAX_CARDS = 40
CARDS_PER_BATCH = 8

FLASHCARD_SYSTEM = """Create exactly {count} study flashcards STRICTLY from the document excerpts below.
- "front": a short prompt (a term, concept or question), max ~15 words.
- "back": a precise answer of 1-3 sentences using only the excerpt's content.
- "page": the integer page number from the [p. X] tag of the source excerpt.
- Prefer key definitions, facts, numbers, causes/effects and processes. No duplicates.
- {language}
Return ONLY JSON (no fences): {{"cards": [{{"front": "...", "back": "...", "page": 2}}]}}

Document excerpts:
{context}"""

_prompt = ChatPromptTemplate.from_messages([("system", FLASHCARD_SYSTEM), ("human", "Create the flashcards now.")])


def parse_cards(raw: str) -> list[Flashcard]:
    data = extract_json(raw)
    items = data.get("cards", []) if isinstance(data, dict) else data
    cards: list[Flashcard] = []
    for item in items if isinstance(items, list) else []:
        try:
            cards.append(Flashcard.model_validate(item))
        except ValidationError:
            continue
    return cards


async def _batch(docs: Sequence[Document], count: int, language: str, settings: Settings) -> list[Flashcard]:
    chain = _prompt | get_chat_model(settings.quiz_temperature) | StrOutputParser()
    for attempt in range(2):
        try:
            cards = parse_cards(await chain.ainvoke({
                "count": count,
                "language": language_instruction(language) + " Keep JSON keys in English.",
                "context": format_context(docs),
            }))
            if cards:
                return cards
        except Exception as exc:
            logger.warning("Flashcard batch attempt %d failed: %s", attempt + 1, exc)
    return []


async def generate_flashcards(
    *,
    doc_id: str,
    num_cards: int | None,
    topic: str | None,
    language: str,
    settings: Settings,
    vectorstore: VectorStoreManager,
) -> AsyncIterator[Event]:
    n = min(num_cards or DEFAULT_CARDS, MAX_CARDS)
    batches = math.ceil(n / CARDS_PER_BATCH)
    yield status("Picking key passages...")
    docs = await select_chunks(doc_id=doc_id, topic=topic, needed=batches * 4, vectorstore=vectorstore)
    if not docs:
        yield {"type": "token", "content": settings.not_found_message}
        return

    groups = split_evenly(docs, batches)
    counts = [len(c) for c in split_evenly(range(n), len(groups))]
    yield status(f"Writing {n} flashcards...")
    semaphore = asyncio.Semaphore(settings.map_concurrency)

    async def run(group: list[Document], count: int) -> list[Flashcard]:
        async with semaphore:
            return await _batch(group, count, language, settings)

    seen: set[str] = set()
    cards: list[Flashcard] = []
    for batch in await asyncio.gather(*(run(g, c) for g, c in zip(groups, counts))):
        for card in batch:
            key = card.front.strip().lower()
            if key not in seen:
                seen.add(key)
                cards.append(card)

    if not cards:
        yield {"type": "error", "message": "Could not generate flashcards. Please try again."}
        return
    deck = FlashcardDeck(title=f"Flashcards: {topic}" if topic else "Document flashcards", cards=cards[:n])
    yield {"type": "flashcards", "flashcards": deck.model_dump()}
