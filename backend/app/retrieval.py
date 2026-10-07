"""Hybrid retrieval: BM25 keywords + dense vectors, fused with RRF, then cross-encoder reranking.

Why both: embeddings capture meaning ("salary" ~ "compensation") but blur exact tokens such as
course codes, IDs, clause numbers or names ("CSC336", "FR02-01"). BM25 nails those. Reciprocal
rank fusion merges the two rankings without score calibration, and the cross-encoder then reads
each (query, passage) pair together for a much sharper final ordering.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.documents import Document
from rank_bm25 import BM25Plus

from app.config import Settings
from app.vectorstore import VectorStoreManager, export_hf_token

logger = logging.getLogger(__name__)

RRF_K = 60
_TOKEN = re.compile(r"\w+", re.UNICODE)  # \w covers Urdu/Arabic script too
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were what "
    "when where which who why how with does did do i you me my your our we they he she them his her "
    "ka ki ke ko hai hain kya mein main se aur ye yeh wo".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class _BM25Index:
    # BM25+ keeps IDF positive even for tiny documents (classic BM25 scores a term found in
    # 1 of 2 chunks as zero), so short PDFs still get keyword matches.
    generation: int
    bm25: BM25Plus | None
    docs: list[Document]
    terms: list[set[str]]


class Reranker:
    """Lazy, thread-safe CrossEncoder wrapper. Disabled when no model is configured or it fails to load.

    Loading (and the first-time model download) happens in the background: until the model is
    ready, searches simply skip reranking instead of making the user wait.
    """

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.reranker_model.strip()
        self.device = settings.embedding_device
        self.settings = settings
        self._model = None
        self._failed = not self.model_name
        self._loading = False
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return not self._failed

    @property
    def ready(self) -> bool:
        return self._model is not None

    def _load(self):  # noqa: ANN202 - sentence_transformers type is optional at import time
        with self._lock:
            if self._model is None and not self._failed:
                try:
                    export_hf_token(self.settings)
                    from sentence_transformers import CrossEncoder

                    self._model = CrossEncoder(self.model_name, device=self.device, max_length=512)
                    logger.info("Reranker loaded: %s", self.model_name)
                except Exception:
                    logger.exception("Could not load reranker %s; continuing without it", self.model_name)
                    self._failed = True
            self._loading = False
        return self._model

    def warm_up(self) -> None:
        """Blocking load (startup thread, evaluation)."""
        self._load()

    def _load_in_background(self) -> None:
        with self._lock:
            if self._loading or self._model is not None or self._failed:
                return
            self._loading = True
        threading.Thread(target=self._load, name="reranker-load", daemon=True).start()

    def rerank(self, query: str, docs: Sequence[Document], top_k: int) -> list[Document]:
        model = self._model
        if model is None or not docs:
            self._load_in_background()
            return list(docs)[:top_k]
        scores = model.predict([(query, d.page_content) for d in docs], show_progress_bar=False)
        ranked = sorted(zip(docs, scores), key=lambda pair: float(pair[1]), reverse=True)
        out = []
        for doc, score in ranked[:top_k]:
            doc.metadata["rerank_score"] = round(float(score), 4)
            out.append(doc)
        return out


class HybridRetriever:
    def __init__(self, settings: Settings, vectorstore: VectorStoreManager, reranker: Reranker | None = None) -> None:
        self.settings = settings
        self.vectorstore = vectorstore
        self.reranker = reranker if reranker is not None else Reranker(settings)
        self._bm25: dict[str, _BM25Index] = {}
        self._lock = threading.Lock()

    # --- BM25 ---------------------------------------------------------------------

    def _bm25_index(self, doc_id: str) -> _BM25Index:
        generation = self.vectorstore.generation.get(doc_id, 0)
        with self._lock:
            cached = self._bm25.get(doc_id)
            if cached and cached.generation == generation:
                return cached
        docs = self.vectorstore.all_chunks(doc_id)
        corpus = [tokenize(d.page_content) for d in docs]
        bm25 = BM25Plus(corpus) if any(corpus) else None
        index = _BM25Index(generation=generation, bm25=bm25, docs=docs, terms=[set(c) for c in corpus])
        with self._lock:
            self._bm25[doc_id] = index
        return index

    def keyword_search(self, doc_id: str, query: str, k: int) -> list[Document]:
        index = self._bm25_index(doc_id)
        terms = tokenize(query)
        if index.bm25 is None or not terms:
            return []
        scores = index.bm25.get_scores(terms)
        wanted = set(terms)
        # BM25+ gives every chunk a small baseline score; only chunks sharing a term are real hits.
        matching = [i for i in range(len(scores)) if index.terms[i] & wanted]
        ranked = sorted(matching, key=lambda i: scores[i], reverse=True)
        return [index.docs[i] for i in ranked[:k]]

    # --- Fusion -----------------------------------------------------------------------

    @staticmethod
    def fuse(rankings: Sequence[Sequence[Document]]) -> list[Document]:
        """Reciprocal rank fusion keyed by chunk id."""
        scores: dict[str, float] = {}
        by_id: dict[str, Document] = {}
        for ranking in rankings:
            for rank, doc in enumerate(ranking):
                key = str(doc.metadata.get("chunk_id")) or doc.page_content[:80]
                scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
                by_id.setdefault(key, doc)
        return [by_id[key] for key in sorted(scores, key=scores.__getitem__, reverse=True)]

    def search(self, doc_ids: Sequence[str], query: str, *, k: int | None = None) -> list[Document]:
        """Top-k chunks for `query` across one or more documents (best first)."""
        k = k or self.settings.retrieval_k
        per_method = self.settings.retrieval_fetch_k
        rankings: list[list[Document]] = []
        for doc_id in doc_ids:
            rankings.append(self.vectorstore.similarity_search(doc_id, query, k=per_method))
            rankings.append(self.keyword_search(doc_id, query, per_method))
        candidates = self.fuse(rankings)[: max(self.settings.rerank_candidates, k)]
        if self.reranker.enabled:
            return self.reranker.rerank(query, candidates, k)
        return candidates[:k]
