"""Intent router: a small LLM call returning JSON, with a regex fallback.

The heuristic router also fills in parameters the LLM leaves out (e.g. the
number of questions), so the pipeline never depends on a single brittle call.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.chains.common import extract_json
from app.schemas import ChatTurn, Intent, RouteResult, RouterParams

logger = logging.getLogger(__name__)

ROUTER_SYSTEM = """You classify messages sent to a chat-with-a-PDF assistant.
Return ONLY a JSON object, no prose, no code fences:
{{"intent": "QA|SUMMARY|QUIZ|FLASHCARDS|NOTES|EXPLAIN|OUT_OF_SCOPE",
 "params": {{"num_questions": int|null, "difficulty": "easy|medium|hard"|null, "topic": string|null,
            "language": "english|urdu|hinglish", "question_type": "mcq|true_false|short|mixed"|null,
            "summary_style": "short|detailed|bullet"|null}}}}

Intents:
- QA: a question about the document's content (facts, definitions, "what does it say about X"). Default when unsure.
- SUMMARY: summarize / overview / key points / TL;DR of the document or a part of it.
- QUIZ: create a quiz, test, MCQs, true/false or practice questions.
- FLASHCARDS: create flashcards.
- NOTES: create study notes / revision notes / study guide.
- EXPLAIN: explain or simplify a concept in depth, teach it step by step ("explain X", "samjhao").
- OUT_OF_SCOPE: ONLY greetings, thanks, small talk, or tasks that cannot involve a document (jokes, coding help).
  The document is often the user's own (result card, CV, bill, contract), so questions about "my" grades,
  marks, salary, dates, etc. are QA, not OUT_OF_SCOPE.

Params:
- topic: the specific subject/chapter/section the user restricts the request to, else null.
- language: "urdu" if written in Urdu script, "hinglish" if Roman Urdu/Hindi mixed with English, else "english".
- summary_style: "bullet" for key points/bullets, "short" for brief/TL;DR, "detailed" for in-depth.
- Only set num_questions/difficulty/question_type/summary_style when the user states them; a plain
  "summarize" has summary_style null."""

_router_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", ROUTER_SYSTEM),
        ("human", "Recent conversation:\n{history}\n\nMessage to classify:\n{message}"),
    ]
)

# --- Heuristics ---------------------------------------------------------------

_I = re.I
_PATTERNS: list[tuple[Intent, re.Pattern[str]]] = [
    (Intent.FLASHCARDS, re.compile(r"flash\s?-?cards?", _I)),
    (Intent.QUIZ, re.compile(
        r"\bquiz|\bmcqs?\b|multiple[- ]choice|true\s*(?:/|or)\s*false|\btest me\b|\bimtihan|"
        r"practice questions|(?:questions?|sawal(?:at)?)\s+(?:banao|bana do|bnao|generate|create|make)|"
        r"(?:generate|create|make|give me)\s+(?:\d+\s+)?(?:\w+\s+)?questions", _I)),
    (Intent.NOTES, re.compile(r"\bnotes\b|study guide|revision sheet|cheat ?sheet", _I)),
    (Intent.SUMMARY, re.compile(
        r"summar|overview|\btl;?dr\b|\bgist\b|key (?:points|takeaways)|main points|khulasa|خلاصہ|"
        r"in short\b|what is this (?:document|pdf|file) about", _I)),
    (Intent.EXPLAIN, re.compile(
        r"\bexplain|samjha|samjh(?:ao|a do)|\beli5\b|in simple (?:words|terms)|break (?:it )?down|"
        r"simplify|teach me|وضاحت|سمجھا", _I)),
]
_GREETING = re.compile(
    r"^\s*(hi+|hello|hey|salam|assalam[- ]?o[- ]?alaikum|aoa|good (?:morning|evening|afternoon)|"
    r"thanks?(?: you)?|thank u|shukriya|ok(?:ay)?|bye)[\s!.?]*$", _I)
_OFF_TOPIC = re.compile(r"\b(weather|tell me a joke|who are you|what can you do|write (?:me )?code)\b", _I)

_NUM = re.compile(
    r"\b(\d{1,2})[\s-]*(?:[\w/-]+\s+){0,3}?(?:mcqs?|questions?|qs\b|sawal|quiz|flash\s?-?cards?|cards?|items?)", _I)
_DIFFICULTY = re.compile(r"\b(easy|medium|hard|difficult|tough|asaan|mushkil|advanced|beginner)\b", _I)
_QTYPE = [
    ("true_false", re.compile(r"true\s*(?:/|or)\s*false|\bt/f\b", _I)),
    ("short", re.compile(r"short[- ]answer|short questions|subjective", _I)),
    ("mixed", re.compile(r"\bmix(?:ed)?\b", _I)),
    ("mcq", re.compile(r"\bmcqs?\b|multiple[- ]choice", _I)),
]
_STYLE = [
    ("bullet", re.compile(r"bullet|key (?:points|takeaways)|main points|points", _I)),
    ("short", re.compile(r"\bshort\b|brief|tl;?dr|one paragraph|quick|mukhtasar", _I)),
    ("detailed", re.compile(r"detail|comprehensive|in depth|in-depth|thorough|tafseel", _I)),
]
_TOPIC = re.compile(
    r"\b(?:on|about|regarding|related to|from|of)\s+(?:the\s+)?(?P<topic>(?:chapter|section|topic|part)?\s*[^?.!,]{3,80})",
    _I)
_TOPIC_TAIL = re.compile(r"\s+(?:with|in|for|and|please|plz|pls|using|at)\b", _I)
_TOPIC_STOP = re.compile(r"^(?:this|the|that|whole|entire|my|it)\b.*(?:document|pdf|file|book|paper)?$", _I)

_URDU_SCRIPT = re.compile(r"[؀-ۿ]")
_ROMAN_URDU = {
    "hai", "hain", "kya", "kia", "ka", "ki", "ke", "ko", "mein", "mai", "nahi", "nahin", "kaise",
    "kaisay", "kyun", "kyon", "batao", "btao", "bataen", "bataiye", "karo", "kro", "kar", "yeh", "ye",
    "wo", "woh", "aur", "se", "par", "pe", "ho", "hoga", "chahiye", "samjhao", "banao", "bnao", "mujhe",
    "kitne", "kitna", "konsa", "kaun", "sawal", "dein", "hy", "hn", "acha", "theek", "ap", "aap",
}


def detect_language(text: str) -> str:
    if _URDU_SCRIPT.search(text):
        return "urdu"
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return "english"
    hits = sum(1 for w in words if w in _ROMAN_URDU)
    if hits >= 2 or (hits == 1 and len(words) <= 4) or hits / len(words) >= 0.2:
        return "hinglish"
    return "english"


def extract_params(message: str) -> RouterParams:
    params: dict[str, Any] = {"language": detect_language(message)}
    if m := _NUM.search(message):
        params["num_questions"] = int(m.group(1))
    if m := _DIFFICULTY.search(message):
        params["difficulty"] = m.group(1)
    params["question_type"] = next((t for t, p in _QTYPE if p.search(message)), None)
    params["summary_style"] = next((s for s, p in _STYLE if p.search(message)), None)
    for m in _TOPIC.finditer(message):
        topic = _TOPIC_TAIL.split(m.group("topic"))[0].strip()
        if topic and not topic[0].isdigit() and not _TOPIC_STOP.match(topic):
            params["topic"] = topic
            break
    return RouterParams.model_validate(params)


def heuristic_route(message: str) -> RouteResult:
    params = extract_params(message)
    if _GREETING.match(message) or _OFF_TOPIC.search(message):
        intent = Intent.OUT_OF_SCOPE
    else:
        intent = next((i for i, p in _PATTERNS if p.search(message)), Intent.QA)
    if intent in (Intent.QA, Intent.OUT_OF_SCOPE):
        params.topic = None
    return RouteResult(intent=intent, params=params, source="heuristic")


def parse_router_output(raw: str) -> RouteResult:
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("router output is not a JSON object")
    intent = Intent(str(data.get("intent", "")).strip().upper())
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return RouteResult(intent=intent, params=RouterParams.model_validate(params), source="llm")


def merge_params(primary: RouterParams, fallback: RouterParams) -> RouterParams:
    merged = primary.model_dump()
    for key, value in fallback.model_dump().items():
        if merged.get(key) is None and value is not None:
            merged[key] = value
    return RouterParams.model_validate(merged)


class IntentRouter:
    def __init__(self, llm: BaseChatModel | None) -> None:
        self.chain = (_router_prompt | llm | StrOutputParser()) if llm is not None else None

    async def aroute(self, message: str, history: list[ChatTurn] | None = None) -> RouteResult:
        fallback = heuristic_route(message)
        if self.chain is None:
            return fallback
        recent = "\n".join(f"{t.role}: {t.content[:300]}" for t in (history or [])[-4:]) or "(none)"
        try:
            raw = await self.chain.ainvoke({"history": recent, "message": message})
            result = parse_router_output(raw)
        except Exception as exc:
            logger.warning("Router LLM failed (%s); using heuristic intent %s", exc, fallback.intent.value)
            return fallback

        # A wrongly refused question is worse than a QA pass that says "not found", so only
        # refuse when the keyword check agrees (greetings, jokes, ...).
        if result.intent == Intent.OUT_OF_SCOPE and fallback.intent != Intent.OUT_OF_SCOPE:
            result.intent = fallback.intent

        # Small models tend to invent "short" for a plain "summarize"; keep a brief style only
        # when the user's own words asked for it (detailed is the default).
        if result.params.summary_style == "short" and fallback.params.summary_style != "short":
            result.params.summary_style = None

        # The script detector is more reliable than the model for Urdu vs Roman Urdu.
        if fallback.params.language != "english":
            result.params.language = fallback.params.language
        result.params = merge_params(result.params, fallback.params)
        logger.info("Routed %r -> %s %s", message[:80], result.intent.value, result.params.model_dump(exclude_none=True))
        return result
