"""Pydantic schemas shared by the API, router and chains."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Difficulty = Literal["easy", "medium", "hard"]
QuestionType = Literal["mcq", "true_false", "short"]
SummaryStyle = Literal["short", "detailed", "bullet"]
Language = Literal["english", "urdu", "hinglish"]


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class ChunkConfig(BaseModel):
    strategy: Literal["short", "notes", "slides", "general", "technical"]
    chunk_size: int
    chunk_overlap: int
    reason: str


class DocumentProfile(BaseModel):
    page_count: int
    total_words: int
    avg_words_per_page: float
    heading_count: int
    heading_density: float  # headings per page
    table_count: int
    table_ratio: float  # share of pages that contain a table
    bullet_ratio: float  # share of text blocks that are list items
    ocr_pages: int
    is_scanned: bool
    technical_score: int
    doc_type: str


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    size_bytes: int
    page_count: int
    chunk_count: int
    total_chars: int = 0
    created_at: datetime
    chunk_config: ChunkConfig
    profile: DocumentProfile
    embedding_id: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class Intent(str, Enum):
    QA = "QA"
    SUMMARY = "SUMMARY"
    QUIZ = "QUIZ"
    FLASHCARDS = "FLASHCARDS"
    NOTES = "NOTES"
    EXPLAIN = "EXPLAIN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


def _none_if_blank(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().lower()
        return value or None
    return value


def normalize_question_type(value: Any) -> str | None:
    v = _none_if_blank(value)
    aliases = {"multiple_choice": "mcq", "multiple choice": "mcq", "mcqs": "mcq",
               "true/false": "true_false", "tf": "true_false", "truefalse": "true_false",
               "true or false": "true_false", "short_answer": "short", "short answer": "short",
               "mix": "mixed"}
    v = aliases.get(v, v)
    return v if v in ("mcq", "true_false", "short", "mixed") else None


class RouterParams(BaseModel):
    """Optional knobs extracted from the user's request. Garbage values become None."""

    num_questions: int | None = None
    difficulty: Difficulty | None = None
    topic: str | None = None
    language: Language | None = None
    question_type: Literal["mcq", "true_false", "short", "mixed"] | None = None
    summary_style: SummaryStyle | None = None

    @field_validator("num_questions", mode="before")
    @classmethod
    def _clamp_num(cls, v: Any) -> int | None:
        if v in (None, "", "null"):
            return None
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        return max(1, min(n, 30)) if n > 0 else None

    @field_validator("difficulty", mode="before")
    @classmethod
    def _difficulty(cls, v: Any) -> str | None:
        v = _none_if_blank(v)
        aliases = {"asaan": "easy", "simple": "easy", "beginner": "easy", "normal": "medium",
                   "moderate": "medium", "difficult": "hard", "tough": "hard", "mushkil": "hard",
                   "advanced": "hard"}
        v = aliases.get(v, v)
        return v if v in ("easy", "medium", "hard") else None

    @field_validator("language", mode="before")
    @classmethod
    def _language(cls, v: Any) -> str | None:
        v = _none_if_blank(v)
        aliases = {"en": "english", "ur": "urdu", "roman urdu": "hinglish", "roman_urdu": "hinglish",
                   "roman-urdu": "hinglish", "hindi": "hinglish", "urdu (roman)": "hinglish"}
        v = aliases.get(v, v)
        return v if v in ("english", "urdu", "hinglish") else None

    @field_validator("question_type", mode="before")
    @classmethod
    def _qtype(cls, v: Any) -> str | None:
        return normalize_question_type(v)

    @field_validator("summary_style", mode="before")
    @classmethod
    def _style(cls, v: Any) -> str | None:
        v = _none_if_blank(v)
        aliases = {"brief": "short", "tldr": "short", "long": "detailed", "bullets": "bullet",
                   "bullet_points": "bullet", "points": "bullet"}
        v = aliases.get(v, v)
        return v if v in ("short", "detailed", "bullet") else None

    @field_validator("topic", mode="before")
    @classmethod
    def _topic(cls, v: Any) -> str | None:
        if not isinstance(v, str):
            return None
        v = v.strip().strip("\"'.?!")
        if not v or v.lower() in {"null", "none", "all", "whole document", "document", "the document"}:
            return None
        return v[:200]


class RouteResult(BaseModel):
    intent: Intent
    params: RouterParams = Field(default_factory=RouterParams)
    source: Literal["llm", "heuristic"] = "llm"


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    doc_id: str = Field(min_length=4, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=50)


class SourceChunk(BaseModel):
    chunk_id: str
    chunk_index: int
    page: int
    page_end: int
    section: str | None = None
    kind: str = "text"
    has_table: bool = False
    text: str


# ---------------------------------------------------------------------------
# Quiz / flashcards
# ---------------------------------------------------------------------------

_OPTION_PREFIX = re.compile(r"^\s*(?:\(?[A-Fa-f][\.\):]|\d[\.\)])\s+")
_TRUE = {"true", "t", "yes", "sahi", "sach", "correct", "صحیح", "درست"}
_FALSE = {"false", "f", "no", "ghalat", "galat", "jhoot", "incorrect", "غلط"}


def _coerce_page(v: Any) -> int:
    if isinstance(v, int):
        return max(v, 1)
    match = re.search(r"\d+", str(v or ""))
    return max(int(match.group()), 1) if match else 1


class QuizQuestion(BaseModel):
    question: str = Field(min_length=5)
    type: QuestionType
    options: list[str] = Field(default_factory=list)
    correct_answer: str = Field(min_length=1)
    explanation: str = ""
    page: int = 1

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v: Any) -> Any:
        return normalize_question_type(v) if isinstance(v, str) else v

    @field_validator("page", mode="before")
    @classmethod
    def _page(cls, v: Any) -> int:
        return _coerce_page(v)

    @field_validator("options", mode="before")
    @classmethod
    def _options(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        cleaned = [_OPTION_PREFIX.sub("", str(o)).strip() for o in v if str(o).strip()]
        return list(dict.fromkeys(cleaned))  # drop duplicates, keep order

    @model_validator(mode="after")
    def _consistency(self) -> "QuizQuestion":
        answer = str(self.correct_answer).strip()
        if self.type == "mcq":
            if not 3 <= len(self.options) <= 6:
                raise ValueError("mcq needs 3-6 distinct options")
            letter = re.fullmatch(r"\(?([A-Fa-f])[\.\)]?", answer)
            if letter:
                idx = ord(letter.group(1).upper()) - ord("A")
                if idx >= len(self.options):
                    raise ValueError("answer letter out of range")
                answer = self.options[idx]
            else:
                stripped = _OPTION_PREFIX.sub("", answer).strip().lower()
                match = next((o for o in self.options if o.lower() == stripped), None)
                if match is None:
                    raise ValueError("correct_answer must be one of the options")
                answer = match
        elif self.type == "true_false":
            low = answer.lower().strip(".")
            if low in _TRUE:
                answer = "True"
            elif low in _FALSE:
                answer = "False"
            else:
                raise ValueError("true_false answer must be True or False")
            self.options = ["True", "False"]
        else:
            self.options = []
        self.correct_answer = answer
        return self


class Quiz(BaseModel):
    title: str
    difficulty: Difficulty
    questions: list[QuizQuestion]


class Flashcard(BaseModel):
    front: str = Field(min_length=2)
    back: str = Field(min_length=1)
    page: int = 1

    @field_validator("page", mode="before")
    @classmethod
    def _page(cls, v: Any) -> int:
        return _coerce_page(v)


class FlashcardDeck(BaseModel):
    title: str
    cards: list[Flashcard]


class GradeItem(BaseModel):
    question: str
    type: QuestionType
    options: list[str] = Field(default_factory=list)
    correct_answer: str
    user_answer: str = Field(default="", max_length=2000)
    explanation: str = ""
    page: int | None = None


class GradeRequest(BaseModel):
    doc_id: str | None = None
    items: list[GradeItem] = Field(min_length=1, max_length=50)


class GradeResult(BaseModel):
    index: int
    correct: bool
    score: float = Field(ge=0, le=1)
    feedback: str


class GradeResponse(BaseModel):
    results: list[GradeResult]
    total_score: float
    max_score: int
    percentage: float


class HealthResponse(BaseModel):
    status: Literal["ok"]
    llm_provider: str
    llm_model: str
    router_model: str
    embedding_model: str
    llm_configured: bool
    documents: int
