"""Unit tests for the intent router (heuristics, LLM JSON parsing, fallbacks)."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.language_models import FakeListChatModel

from app.router import IntentRouter, detect_language, extract_params, heuristic_route, parse_router_output
from app.schemas import Intent, RouterParams


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("What is the main finding of the study?", Intent.QA),
        ("Summarize this document", Intent.SUMMARY),
        ("Give me the key points", Intent.SUMMARY),
        ("Generate a quiz", Intent.QUIZ),
        ("make 5 hard MCQs on chapter 2", Intent.QUIZ),
        ("Is ka khulasa batao", Intent.SUMMARY),
        ("10 sawal banao", Intent.QUIZ),
        ("Create flashcards", Intent.FLASHCARDS),
        ("Make study notes on photosynthesis", Intent.NOTES),
        ("Explain gradient descent in simple words", Intent.EXPLAIN),
        ("hello!", Intent.OUT_OF_SCOPE),
        ("tell me a joke", Intent.OUT_OF_SCOPE),
    ],
)
def test_heuristic_intents(message: str, intent: Intent) -> None:
    assert heuristic_route(message).intent == intent


def test_extract_quiz_params() -> None:
    p = extract_params("Generate 15 hard true/false questions on cell division")
    assert p.num_questions == 15
    assert p.difficulty == "hard"
    assert p.question_type == "true_false"
    assert p.topic == "cell division"


def test_number_without_topic_is_not_a_topic() -> None:
    p = extract_params("quiz of 10 questions")
    assert p.num_questions == 10
    assert p.topic is None


def test_summary_style() -> None:
    assert extract_params("give a brief summary").summary_style == "short"
    assert extract_params("detailed summary please").summary_style == "detailed"
    assert extract_params("key points").summary_style == "bullet"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("What is the conclusion?", "english"),
        ("Is document ka main point kya hai?", "hinglish"),
        ("اس دستاویز کا خلاصہ کیا ہے؟", "urdu"),
    ],
)
def test_detect_language(text: str, language: str) -> None:
    assert detect_language(text) == language


def test_params_are_clamped_and_normalized() -> None:
    p = RouterParams.model_validate(
        {"num_questions": "100", "difficulty": "Difficult", "question_type": "Multiple Choice",
         "language": "Roman Urdu", "summary_style": "bullets", "topic": "  "}
    )
    assert p.num_questions == 30
    assert p.difficulty == "hard"
    assert p.question_type == "mcq"
    assert p.language == "hinglish"
    assert p.summary_style == "bullet"
    assert p.topic is None


def test_garbage_params_become_none() -> None:
    p = RouterParams.model_validate({"num_questions": "lots", "difficulty": "extreme", "language": "klingon"})
    assert (p.num_questions, p.difficulty, p.language) == (None, None, None)


def test_parse_router_output_with_fences() -> None:
    raw = '```json\n{"intent": "quiz", "params": {"num_questions": 5, "difficulty": "easy"}}\n```'
    result = parse_router_output(raw)
    assert result.intent == Intent.QUIZ
    assert result.params.num_questions == 5
    assert result.params.difficulty == "easy"


def test_router_uses_llm_and_fills_missing_params() -> None:
    llm = FakeListChatModel(responses=['{"intent": "QUIZ", "params": {"difficulty": "hard"}}'])
    result = asyncio.run(IntentRouter(llm).aroute("make 7 tough questions"))
    assert result.source == "llm"
    assert result.intent == Intent.QUIZ
    assert result.params.difficulty == "hard"
    assert result.params.num_questions == 7  # filled in by the heuristic extractor


def test_router_falls_back_on_invalid_json() -> None:
    llm = FakeListChatModel(responses=["Sure! This looks like a summary request."])
    result = asyncio.run(IntentRouter(llm).aroute("Summarize chapter 3"))
    assert result.source == "heuristic"
    assert result.intent == Intent.SUMMARY


def test_router_falls_back_on_unknown_intent() -> None:
    llm = FakeListChatModel(responses=['{"intent": "TRANSLATE", "params": {}}'])
    result = asyncio.run(IntentRouter(llm).aroute("What does the author conclude?"))
    assert result.intent == Intent.QA


def test_script_language_overrides_llm() -> None:
    llm = FakeListChatModel(responses=['{"intent": "QA", "params": {"language": "english"}}'])
    result = asyncio.run(IntentRouter(llm).aroute("Is chapter ka main idea kya hai?"))
    assert result.params.language == "hinglish"


def test_llm_out_of_scope_overridden_for_document_questions() -> None:
    llm = FakeListChatModel(responses=['{"intent": "OUT_OF_SCOPE", "params": {}}'])
    result = asyncio.run(IntentRouter(llm).aroute("whats my cgpa in last semester"))
    assert result.intent == Intent.QA


def test_llm_out_of_scope_kept_for_greetings() -> None:
    llm = FakeListChatModel(responses=['{"intent": "OUT_OF_SCOPE", "params": {}}'])
    result = asyncio.run(IntentRouter(llm).aroute("hello!"))
    assert result.intent == Intent.OUT_OF_SCOPE


def test_plain_summarize_is_not_forced_short() -> None:
    llm = FakeListChatModel(responses=['{"intent": "SUMMARY", "params": {"summary_style": "short"}}'])
    assert asyncio.run(IntentRouter(llm).aroute("Summarize this document")).params.summary_style is None
    llm = FakeListChatModel(responses=['{"intent": "SUMMARY", "params": {"summary_style": "short"}}'])
    assert asyncio.run(IntentRouter(llm).aroute("give me a brief summary")).params.summary_style == "short"


def test_router_without_llm_is_heuristic() -> None:
    result = asyncio.run(IntentRouter(None).aroute("Make flashcards"))
    assert result.intent == Intent.FLASHCARDS
    assert result.source == "heuristic"
