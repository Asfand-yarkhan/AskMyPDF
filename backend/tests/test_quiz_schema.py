"""Quiz JSON validation: the contract the frontend relies on."""

from __future__ import annotations

from app.chains.quiz import parse_questions
from app.schemas import QuizQuestion


def test_mcq_letter_answer_is_mapped_to_option() -> None:
    q = QuizQuestion.model_validate({
        "question": "What is the capital?", "type": "mcq",
        "options": ["A) Paris", "B) Rome", "C) Oslo", "D) Lima"], "correct_answer": "B", "page": "p. 4",
    })
    assert q.options == ["Paris", "Rome", "Oslo", "Lima"]
    assert q.correct_answer == "Rome"
    assert q.page == 4


def test_true_false_normalized() -> None:
    q = QuizQuestion.model_validate({"question": "The sky is green?", "type": "True/False", "correct_answer": "false"})
    assert q.type == "true_false"
    assert q.options == ["True", "False"]
    assert q.correct_answer == "False"


def test_invalid_items_dropped_valid_kept() -> None:
    raw = """{"questions": [
      {"question": "Valid one here?", "type": "mcq", "options": ["a", "b", "c", "d"], "correct_answer": "c", "page": 2},
      {"question": "Answer not in options?", "type": "mcq", "options": ["a", "b", "c", "d"], "correct_answer": "z"},
      {"question": "Define osmosis.", "type": "short", "correct_answer": "Movement of water across a membrane."}
    ]}"""
    valid, errors = parse_questions(raw)
    assert [q.type for q in valid] == ["mcq", "short"]
    assert len(errors) == 1
