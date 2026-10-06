"""Chat orchestration: route the message, then stream events from the matching chain."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.chains import qa, quiz, study, summary
from app.chains.common import Event, token
from app.config import Settings
from app.llm import LLMConfigError, get_chat_model, llm_configured
from app.router import IntentRouter
from app.schemas import ChatRequest, DocumentInfo, Intent, RouteResult
from app.vectorstore import VectorStoreManager

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


class ChatOrchestrator:
    def __init__(self, settings: Settings, vectorstore: VectorStoreManager) -> None:
        self.settings = settings
        self.vectorstore = vectorstore

    def _router(self) -> IntentRouter:
        return IntentRouter(get_chat_model(0.0, "router") if llm_configured() else None)

    async def stream(self, request: ChatRequest, doc: DocumentInfo) -> AsyncIterator[Event]:
        try:
            route = await self._router().aroute(request.message, request.history)
            yield {
                "type": "intent",
                "intent": route.intent.value,
                "params": route.params.model_dump(exclude_none=True),
            }
            async for event in self._dispatch(route, request, doc):
                yield event
        except LLMConfigError as exc:
            yield {"type": "error", "message": str(exc)}
        except Exception as exc:
            logger.exception("Chat failed for doc %s", doc.doc_id)
            yield {"type": "error", "message": f"Something went wrong while generating the answer ({type(exc).__name__})."}
        yield {"type": "done"}

    def _dispatch(self, route: RouteResult, request: ChatRequest, doc: DocumentInfo) -> AsyncIterator[Event]:
        p = route.params
        language = p.language or "english"
        common = {"settings": self.settings, "vectorstore": self.vectorstore, "doc_id": doc.doc_id}
        full_context = 0 < doc.total_chars <= self.settings.full_context_max_chars

        match route.intent:
            case Intent.SUMMARY:
                return summary.stream_summary(
                    filename=doc.filename, mode=p.summary_style or "detailed", topic=p.topic,
                    language=language, **common,
                )
            case Intent.NOTES:
                return summary.stream_summary(
                    filename=doc.filename, mode="notes", topic=p.topic, language=language, **common,
                )
            case Intent.QUIZ:
                return quiz.generate_quiz(
                    num_questions=p.num_questions, difficulty=p.difficulty, question_type=p.question_type,
                    topic=p.topic, language=language, **common,
                )
            case Intent.FLASHCARDS:
                return study.generate_flashcards(
                    num_cards=p.num_questions, topic=p.topic, language=language, **common,
                )
            case Intent.EXPLAIN:
                return qa.stream_answer(
                    question=request.message, history=request.history, language=language,
                    mode="explain", topic=p.topic, full_context=full_context, **common,
                )
            case Intent.OUT_OF_SCOPE:
                return _single(OUT_OF_SCOPE_REPLIES.get(language, OUT_OF_SCOPE_REPLIES["english"]))
            case _:
                return qa.stream_answer(
                    question=request.message, history=request.history, language=language,
                    full_context=full_context, **common,
                )


async def _single(text: str) -> AsyncIterator[Event]:
    yield token(text)
