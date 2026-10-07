"""Chat orchestration: route the message, then stream events from the matching chain."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence

from app.cache import ResponseCache, make_key, normalize_question
from app.chains import qa, quiz, study, summary
from app.chains.common import Event, token
from app.config import Settings
from app.llm import LLMConfigError, get_chat_model, is_rate_limit_error, llm_configured
from app.retrieval import HybridRetriever
from app.router import IntentRouter
from app.schemas import ChatRequest, DocumentInfo, Intent, RouteResult

logger = logging.getLogger(__name__)

OUT_OF_SCOPE_REPLIES: dict[str, str] = {
    "english": (
        "I can only help with the uploaded document. Ask me a question about it, or try "
        "**Summarize**, **Generate quiz**, **Key points** or **Flashcards**."
    ),
    "urdu": "میں صرف اپ لوڈ کی گئی دستاویز کے بارے میں مدد کر سکتا ہوں۔ اس کے بارے میں کوئی سوال پوچھیں، "
            "یا خلاصہ، کوئز یا فلیش کارڈز بنوائیں۔",
    "hinglish": (
        "Main sirf upload ki gayi document ke baare mein madad kar sakta hoon. Is ke baare mein sawal "
        "poochein, ya **Summarize**, **Quiz** ya **Flashcards** try karein."
    ),
}

# Deterministic, expensive intents worth caching. Quizzes/flashcards are not cached: users expect
# a fresh set each time.
CACHEABLE = {Intent.SUMMARY, Intent.NOTES, Intent.QA, Intent.EXPLAIN}
REPLAY_PIECE = 60  # chars per token event when replaying a cached answer


class ChatOrchestrator:
    def __init__(self, settings: Settings, retriever: HybridRetriever, cache: ResponseCache) -> None:
        self.settings = settings
        self.retriever = retriever
        self.cache = cache

    def _router(self) -> IntentRouter:
        return IntentRouter(get_chat_model(0.0, "router") if llm_configured() else None)

    def _cache_key(self, route: RouteResult, request: ChatRequest, docs: Sequence[DocumentInfo]) -> str | None:
        if route.intent not in CACHEABLE:
            return None
        if route.intent in (Intent.QA, Intent.EXPLAIN) and request.history:
            return None  # follow-ups depend on the conversation
        return make_key(
            docs=[(d.doc_id, d.created_at.isoformat()) for d in docs],
            intent=route.intent.value,
            params=route.params.model_dump(),
            # Summaries ignore the exact wording ("Summarize" == "summarize the pdf"); questions don't.
            message=None if route.intent in (Intent.SUMMARY, Intent.NOTES) else normalize_question(request.message),
            model=(self.settings.llm_provider, self.settings.resolved_llm_model, self.settings.embedding_model),
            summary_budget=self.settings.summary_max_input_chars,
        )

    async def stream(self, request: ChatRequest, docs: Sequence[DocumentInfo]) -> AsyncIterator[Event]:
        """`docs[0]` is the active document; the rest are extra documents for Q&A / Explain."""
        primary = docs[0]
        try:
            route = await self._router().aroute(request.message, request.history)
            yield {
                "type": "intent",
                "intent": route.intent.value,
                "params": route.params.model_dump(exclude_none=True),
            }
            scope = docs if route.intent in (Intent.QA, Intent.EXPLAIN) else docs[:1]
            key = self._cache_key(route, request, scope)
            cached = self.cache.get(key) if key else None
            if cached is not None:
                logger.info("Cache hit for %s %r", route.intent.value, request.message[:60])
                yield {"type": "cached"}
                for event in cached:
                    yield event
            else:
                recorded: list[Event] = []
                failed = False
                async for event in self._dispatch(route, request, scope):
                    if event["type"] == "error":
                        failed = True
                    if event["type"] in ("sources", "token"):
                        recorded.append(event)
                    yield event
                answer = "".join(e["content"] for e in recorded if e["type"] == "token")
                if key and not failed and answer.strip() and answer.strip() != self.settings.not_found_message:
                    self.cache.put(key, [d.doc_id for d in scope], _compact(recorded))
        except LLMConfigError as exc:
            yield {"type": "error", "message": str(exc)}
        except Exception as exc:
            if is_rate_limit_error(exc):
                logger.warning("Rate limit exhausted for doc %s: %s", primary.doc_id, exc)
                yield {
                    "type": "error",
                    "message": (
                        f"The AI provider's usage limit ({self.settings.llm_provider} free tier) was reached. "
                        "Please wait about a minute and try again."
                    ),
                }
                yield {"type": "done"}
                return
            logger.exception("Chat failed for doc %s", primary.doc_id)
            yield {"type": "error", "message": f"Something went wrong while generating the answer ({type(exc).__name__})."}
        yield {"type": "done"}

    def _dispatch(self, route: RouteResult, request: ChatRequest, docs: Sequence[DocumentInfo]) -> AsyncIterator[Event]:
        p = route.params
        language = p.language or "english"
        doc = docs[0]
        single = {"settings": self.settings, "retriever": self.retriever, "doc_id": doc.doc_id}

        match route.intent:
            case Intent.SUMMARY:
                return summary.stream_summary(
                    filename=doc.filename, mode=p.summary_style or "detailed", topic=p.topic,
                    language=language, **single,
                )
            case Intent.NOTES:
                return summary.stream_summary(
                    filename=doc.filename, mode="notes", topic=p.topic, language=language, **single,
                )
            case Intent.QUIZ:
                return quiz.generate_quiz(
                    num_questions=p.num_questions, difficulty=p.difficulty, question_type=p.question_type,
                    topic=p.topic, language=language, **single,
                )
            case Intent.FLASHCARDS:
                return study.generate_flashcards(
                    num_cards=p.num_questions, topic=p.topic, language=language, **single,
                )
            case Intent.EXPLAIN:
                return qa.stream_answer(
                    docs=docs, question=request.message, history=request.history, language=language,
                    mode="explain", topic=p.topic, settings=self.settings, retriever=self.retriever,
                )
            case Intent.OUT_OF_SCOPE:
                return _single(OUT_OF_SCOPE_REPLIES.get(language, OUT_OF_SCOPE_REPLIES["english"]))
            case _:
                return qa.stream_answer(
                    docs=docs, question=request.message, history=request.history, language=language,
                    settings=self.settings, retriever=self.retriever,
                )


def _compact(events: list[Event]) -> list[Event]:
    """Store sources once and the answer as a few large token events (fast replay)."""
    sources = [e for e in events if e["type"] == "sources"][-1:]
    text = "".join(e["content"] for e in events if e["type"] == "token")
    pieces = [token(text[i : i + REPLAY_PIECE]) for i in range(0, len(text), REPLAY_PIECE)]
    return sources + pieces


async def _single(text: str) -> AsyncIterator[Event]:
    yield token(text)
