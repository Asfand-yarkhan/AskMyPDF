"""Quiz generation (grounded, Pydantic-validated JSON) and grading."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.chains.common import (
    Event, evenly_sample, extract_json, format_context, language_instruction, split_evenly, status,
    substantive,
)
from app.config import Settings
from app.llm import get_chat_model
from app.schemas import (
    Difficulty, GradeItem, GradeResponse, GradeResult, Quiz, QuizQuestion,
)
from app.retrieval import HybridRetriever

logger = logging.getLogger(__name__)

DEFAULT_QUESTIONS = 10
QUESTIONS_PER_BATCH = 5
CHUNKS_PER_BATCH = 4

DIFFICULTY_GUIDE: dict[str, str] = {
    "easy": "Easy: direct recall of explicitly stated facts and definitions.",
    "medium": "Medium: understanding and relationships between ideas; distractors are plausible.",
    "hard": "Hard: application, comparison and multi-step reasoning across the excerpts; subtle distractors.",
}

TYPE_GUIDE: dict[str, str] = {
    "mcq": "All questions are type \"mcq\" with exactly 4 options. Do NOT write true/false or short-answer questions.",
    "true_false": "All questions are type \"true_false\".",
    "short": "All questions are type \"short\".",
    "mixed": "Mix types: about 60% \"mcq\", 20% \"true_false\", 20% \"short\".",
}

QUIZ_SYSTEM = """You are an expert examiner. Create exactly {count} quiz questions STRICTLY from the \
document excerpts below.

Requirements:
- Every question must be answerable from the excerpts alone. No outside knowledge.
- {difficulty}
- {types}
- "mcq": exactly 4 options, exactly one correct; distractors must be plausible and drawn from the document's \
vocabulary. "correct_answer" must be the full text of one option, copied exactly.
- "true_false": "options" is ["True", "False"] and "correct_answer" is "True" or "False". Make some false.
- "short": "options" is [] and "correct_answer" is a 1-2 sentence model answer.
- "explanation": 1-2 sentences explaining why, based on the excerpt.
- "page": the integer page number from the [p. X] tag of the excerpt that contains the answer.
- Cover different excerpts; do not repeat or paraphrase earlier questions: {avoid}
- {language}

Return ONLY JSON (no Markdown fences, no prose) shaped like:
{{"questions": [{{"question": "...", "type": "mcq", "options": ["...", "...", "...", "..."], \
"correct_answer": "...", "explanation": "...", "page": 3}}]}}

Document excerpts:
{context}"""

_quiz_prompt = ChatPromptTemplate.from_messages([("system", QUIZ_SYSTEM), ("human", "Generate the questions now.")])

GRADE_SYSTEM = """You grade a student's short answer against a reference answer from a document.
Be fair: accept paraphrases and partial wording if the key idea is correct. Ignore spelling mistakes.
Return ONLY JSON: {{"score": number between 0 and 1, "correct": true|false, "feedback": "one or two sentences"}}.
"correct" is true when score >= 0.6. Write the feedback in the same language as the student's answer."""

_grade_prompt = ChatPromptTemplate.from_messages([
    ("system", GRADE_SYSTEM),
    ("human", "Question: {question}\nReference answer: {reference}\nContext: {explanation}\n"
              "Student answer: {answer}"),
])


def parse_questions(raw: str) -> tuple[list[QuizQuestion], list[str]]:
    """Validate each question independently so one bad item does not sink the batch."""
    data: Any = extract_json(raw)
    items = data.get("questions", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("expected a list of questions")
    valid: list[QuizQuestion] = []
    errors: list[str] = []
    for item in items:
        try:
            valid.append(QuizQuestion.model_validate(item))
        except ValidationError as exc:
            errors.append(exc.errors()[0].get("msg", "invalid"))
    return valid, errors


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


async def select_chunks(
    *, doc_id: str, topic: str | None, needed: int, retriever: HybridRetriever
) -> list[Document]:
    """Topic: best-matching chunks (hybrid search). Otherwise: chunks spread evenly over the document."""
    if topic:
        docs = await asyncio.to_thread(retriever.search, [doc_id], topic, k=needed)
        return sorted(docs, key=lambda d: int(d.metadata.get("chunk_index", 0)))
    all_docs = await asyncio.to_thread(retriever.vectorstore.all_chunks, doc_id)
    return evenly_sample(substantive(all_docs), needed)


async def _generate_batch(
    *, docs: Sequence[Document], count: int, difficulty: str, qtype: str, language: str,
    avoid: list[str], settings: Settings,
) -> list[QuizQuestion]:
    chain = _quiz_prompt | get_chat_model(settings.quiz_temperature, "main", "medium") | StrOutputParser()
    inputs = {
        "count": count,
        "difficulty": DIFFICULTY_GUIDE[difficulty],
        "types": TYPE_GUIDE[qtype],
        "avoid": "; ".join(avoid[-15:]) or "(none yet)",
        "language": language_instruction(language) + " Keep the JSON keys and type values in English.",
        "context": format_context(docs),
    }
    for attempt in range(2):
        try:
            questions, errors = parse_questions(await chain.ainvoke(inputs))
            if errors:
                logger.info("Dropped %d invalid quiz items: %s", len(errors), errors[:3])
            if qtype != "mixed":  # models sometimes mix types anyway; keep only what was asked for
                wrong = [q for q in questions if q.type != qtype]
                if wrong:
                    logger.info("Dropped %d quiz items of the wrong type (wanted %s)", len(wrong), qtype)
                questions = [q for q in questions if q.type == qtype]
            if questions:
                return questions
        except Exception as exc:
            logger.warning("Quiz batch attempt %d failed: %s", attempt + 1, exc)
    return []


async def generate_quiz(
    *,
    doc_id: str,
    num_questions: int | None,
    difficulty: Difficulty | None,
    question_type: str | None,
    topic: str | None,
    language: str,
    settings: Settings,
    retriever: HybridRetriever,
) -> AsyncIterator[Event]:
    n = num_questions or DEFAULT_QUESTIONS
    level = difficulty or "medium"
    qtype = question_type or "mcq"
    batches = math.ceil(n / QUESTIONS_PER_BATCH)

    yield status(f"Picking passages {'about ' + repr(topic) if topic else 'from across the document'}...")
    docs = await select_chunks(doc_id=doc_id, topic=topic, needed=batches * CHUNKS_PER_BATCH, retriever=retriever)
    if not docs:
        yield {"type": "token", "content": settings.not_found_message}
        return

    groups = split_evenly(docs, batches)
    counts = [len(c) for c in split_evenly(range(n), len(groups))]
    yield status(f"Writing {n} {level} questions...")

    semaphore = asyncio.Semaphore(settings.map_concurrency)

    async def run(group: list[Document], count: int) -> list[QuizQuestion]:
        async with semaphore:
            return await _generate_batch(
                docs=group, count=count, difficulty=level, qtype=qtype, language=language,
                avoid=[], settings=settings,
            )

    results = await asyncio.gather(*(run(g, c) for g, c in zip(groups, counts)))

    seen: set[str] = set()
    questions: list[QuizQuestion] = []
    for batch in results:
        for q in batch:
            key = _norm(q.question)
            if key not in seen:
                seen.add(key)
                questions.append(q)

    if len(questions) < n:  # top up once from the whole selection
        yield status("Adding a few more questions...")
        extra = await _generate_batch(
            docs=evenly_sample(docs, CHUNKS_PER_BATCH * 2), count=n - len(questions), difficulty=level,
            qtype=qtype, language=language, avoid=[q.question for q in questions], settings=settings,
        )
        questions += [q for q in extra if _norm(q.question) not in seen]

    questions = questions[:n]
    if not questions:
        yield {"type": "error", "message": "Could not generate a valid quiz. Please try again."}
        return
    title = f"Quiz: {topic}" if topic else "Document quiz"
    quiz = Quiz(title=title, difficulty=level, questions=questions)
    yield {"type": "quiz", "quiz": quiz.model_dump()}


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def _grade_objective(item: GradeItem) -> GradeResult:
    correct = _norm(item.user_answer) == _norm(item.correct_answer)
    feedback = "Correct!" if correct else f"The correct answer is: {item.correct_answer}"
    return GradeResult(index=0, correct=correct, score=1.0 if correct else 0.0, feedback=feedback)


async def _grade_short(item: GradeItem) -> GradeResult:
    if not item.user_answer.strip():
        return GradeResult(index=0, correct=False, score=0.0, feedback="No answer given.")
    chain = _grade_prompt | get_chat_model(0.0) | StrOutputParser()
    try:
        data = extract_json(await chain.ainvoke({
            "question": item.question,
            "reference": item.correct_answer,
            "explanation": item.explanation or "-",
            "answer": item.user_answer,
        }))
        score = max(0.0, min(float(data.get("score", 0)), 1.0))
        return GradeResult(index=0, correct=score >= 0.6, score=score, feedback=str(data.get("feedback", "")))
    except Exception as exc:
        logger.warning("Short-answer grading failed, falling back to keyword overlap: %s", exc)
        ref = set(_norm(item.correct_answer).split())
        got = set(_norm(item.user_answer).split())
        score = round(len(ref & got) / max(len(ref), 1), 2)
        return GradeResult(index=0, correct=score >= 0.6, score=score,
                           feedback=f"Reference answer: {item.correct_answer}")


async def grade(items: list[GradeItem]) -> GradeResponse:
    async def one(i: int, item: GradeItem) -> GradeResult:
        result = await _grade_short(item) if item.type == "short" else _grade_objective(item)
        return result.model_copy(update={"index": i})

    results = list(await asyncio.gather(*(one(i, it) for i, it in enumerate(items))))
    total = round(sum(r.score for r in results), 2)
    return GradeResponse(
        results=results, total_score=total, max_score=len(items),
        percentage=round(100 * total / len(items), 1),
    )
