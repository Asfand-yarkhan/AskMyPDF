"""Answer-quality evaluation: ingest the fixtures, ask every question, score the answers.

Metrics
  answer_accuracy   share of questions whose answer contains every expected string
                    (negatives: the answer must be the "not found" message)
  retrieval_hit     share of positive questions where an expected page is among the sources
                    (only for items that list pages)

Run from backend/ (needs an LLM key in .env; uses a separate data dir, eval/.work):
  python -m eval.make_fixtures
  python -m eval.run                    # production settings
  python -m eval.run --retrieval-only   # force top-k retrieval even for small docs
  python -m eval.run --min-accuracy 0.85 --delay 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.cache import ResponseCache
from app.config import get_settings
from app.ingestion.pipeline import ingest_pdf
from app.orchestrator import ChatOrchestrator
from app.registry import DocumentRegistry
from app.retrieval import HybridRetriever
from app.schemas import ChatRequest
from app.vectorstore import VectorStoreManager

HERE = Path(__file__).parent


@dataclass
class Result:
    id: str
    ok: bool
    hit: bool | None
    seconds: float
    answer: str
    pages: list[int] = field(default_factory=list)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


async def ask(orchestrator: ChatOrchestrator, doc, question: str) -> tuple[str, list[int]]:
    answer, pages = "", []
    async for event in orchestrator.stream(ChatRequest(doc_id=doc.doc_id, message=question), [doc]):
        if event["type"] == "token":
            answer += event["content"]
        elif event["type"] == "sources":
            pages = sorted({s["page"] for s in event["sources"]})
        elif event["type"] == "error":
            answer += f" [ERROR: {event['message']}]"
    return answer.strip(), pages


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--retrieval-only", action="store_true", help="disable whole-document mode")
    parser.add_argument("--min-accuracy", type=float, default=0.0, help="exit 1 below this accuracy")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between questions (rate limits)")
    parser.add_argument("--only", help="comma-separated item ids")
    args = parser.parse_args()

    settings = get_settings().model_copy(update={"data_dir": HERE / ".work", "cache_enabled": False})
    if args.retrieval_only:
        settings = settings.model_copy(update={"full_context_max_chars": 0})
    shutil.rmtree(settings.data_dir, ignore_errors=True)
    settings.ensure_dirs()

    missing = [p for p in ("handbook.pdf", "results.pdf") if not (HERE / "fixtures" / p).exists()]
    if missing:
        print("Fixtures missing; run: python -m eval.make_fixtures", file=sys.stderr)
        return 2

    store = VectorStoreManager(settings)
    registry = DocumentRegistry(settings.registry_path)
    retriever = HybridRetriever(settings, store)
    retriever.reranker.warm_up()  # score every question with reranking, not just later ones
    orchestrator = ChatOrchestrator(settings, retriever, ResponseCache(settings.cache_path, 1, enabled=False))

    docs = {}
    for name in ("handbook.pdf", "results.pdf"):
        info, _ = ingest_pdf((HERE / "fixtures" / name).read_bytes(), name, settings=settings, vectorstore=store, registry=registry)
        docs[name] = info
        print(f"Indexed {name}: {info.page_count} pages, {info.chunk_count} chunks ({info.chunk_config.strategy})")

    items = [json.loads(line) for line in (HERE / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        wanted = set(args.only.split(","))
        items = [i for i in items if i["id"] in wanted]

    results: list[Result] = []
    for item in items:
        started = time.perf_counter()
        answer, pages = await ask(orchestrator, docs[item["doc"]], item["question"])
        elapsed = time.perf_counter() - started
        if item.get("negative"):
            ok = norm(settings.not_found_message) in norm(answer)
        else:
            ok = all(norm(e) in norm(answer) for e in item["expect"])
        hit = None if item.get("negative") or "pages" not in item else bool(set(item["pages"]) & set(pages))
        results.append(Result(item["id"], ok, hit, elapsed, answer, pages))
        flag = "PASS" if ok else "FAIL"
        print(f"[{flag}] {item['id']:<16} {elapsed:5.1f}s  pages={pages}  {answer[:90]!r}")
        if args.delay:
            await asyncio.sleep(args.delay)

    accuracy = sum(r.ok for r in results) / max(len(results), 1)
    hits = [r.hit for r in results if r.hit is not None]
    hit_rate = sum(hits) / len(hits) if hits else float("nan")
    print("\n" + "=" * 60)
    print(f"answer_accuracy : {accuracy:.0%}  ({sum(r.ok for r in results)}/{len(results)})")
    print(f"retrieval_hit   : {hit_rate:.0%}  ({sum(hits)}/{len(hits)})")
    print(f"avg latency     : {sum(r.seconds for r in results) / max(len(results), 1):.1f}s")
    print(f"mode            : {'retrieval-only' if args.retrieval_only else 'production'}")
    for r in results:
        if not r.ok:
            print(f"  failed {r.id}: {r.answer[:200]!r}")
    return 1 if accuracy < args.min_accuracy else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
