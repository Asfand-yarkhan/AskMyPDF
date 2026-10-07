"""ChromaDB persistence: one collection per document (keyed by file hash)."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Sequence

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.config import Settings
from app.ingestion.chunker import Chunk

logger = logging.getLogger(__name__)

EMBED_BATCH = 64


class PrefixedEmbeddings(Embeddings):
    """Adds the instruction prefixes some models were trained with (e5: "query: " / "passage: ")."""

    def __init__(self, inner: Embeddings, *, query_prefix: str, document_prefix: str) -> None:
        self.inner = inner
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents([self.document_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(self.query_prefix + text)


def export_hf_token(settings: Settings) -> None:
    if settings.hf_token:
        # huggingface_hub reads the token from the environment, not from our settings.
        os.environ.setdefault("HF_TOKEN", settings.hf_token.get_secret_value())


def build_embeddings(settings: Settings) -> Embeddings:
    provider = settings.embedding_provider
    if provider == "huggingface":
        export_hf_token(settings)
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings: Embeddings = HuggingFaceEmbeddings(
            model_name=settings.embedding_model,
            model_kwargs={"device": settings.embedding_device},
            encode_kwargs={"normalize_embeddings": True},
        )
        if "e5" in settings.embedding_model.lower():
            embeddings = PrefixedEmbeddings(embeddings, query_prefix="query: ", document_prefix="passage: ")
        return embeddings
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIEmbeddings(model=settings.embedding_model, api_key=key, base_url=settings.openai_base_url)
    if provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        key = settings.google_api_key.get_secret_value() if settings.google_api_key else None
        return GoogleGenerativeAIEmbeddings(model=settings.embedding_model, google_api_key=key)
    raise ValueError(f"Unknown embedding provider: {provider}")


class VectorStoreManager:
    def __init__(self, settings: Settings, embeddings: Embeddings | None = None) -> None:
        self.settings = settings
        self.embeddings = embeddings or build_embeddings(settings)
        self.client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._stores: dict[str, Chroma] = {}
        self._lock = threading.Lock()
        # Bumped whenever a document's chunks change, so derived indexes (BM25) know to rebuild.
        self.generation: dict[str, int] = {}

    def _bump(self, doc_id: str) -> None:
        self.generation[doc_id] = self.generation.get(doc_id, 0) + 1

    @staticmethod
    def collection_name(doc_id: str) -> str:
        return f"doc_{doc_id}"

    def store(self, doc_id: str) -> Chroma:
        with self._lock:
            if doc_id not in self._stores:
                self._stores[doc_id] = Chroma(
                    client=self.client,
                    collection_name=self.collection_name(doc_id),
                    embedding_function=self.embeddings,
                    collection_metadata={"hnsw:space": "cosine"},
                )
            return self._stores[doc_id]

    def count(self, doc_id: str) -> int:
        try:
            return self.client.get_collection(self.collection_name(doc_id)).count()
        except Exception:  # collection missing (error type differs across chroma versions)
            return 0

    def add_chunks(
        self,
        doc_id: str,
        chunks: Sequence[Chunk],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        store = self.store(doc_id)
        total = len(chunks)
        for start in range(0, total, EMBED_BATCH):
            batch = chunks[start : start + EMBED_BATCH]
            store.add_texts(
                texts=[c.text for c in batch],
                metadatas=[c.metadata for c in batch],
                ids=[c.metadata["chunk_id"] for c in batch],
            )
            if on_progress:
                on_progress(min(start + EMBED_BATCH, total), total)
        self._bump(doc_id)
        logger.info("Embedded %d chunks for %s", total, doc_id)

    def delete(self, doc_id: str) -> None:
        with self._lock:
            self._stores.pop(doc_id, None)
            self._bump(doc_id)
        try:
            self.client.delete_collection(self.collection_name(doc_id))
        except Exception:
            logger.debug("Collection for %s did not exist", doc_id)

    def all_chunks(self, doc_id: str) -> list[Document]:
        """Every chunk of the document in reading order (for summaries and quizzes)."""
        raw = self.store(doc_id).get(include=["documents", "metadatas"])
        docs = [
            Document(page_content=text, metadata=meta or {})
            for text, meta in zip(raw["documents"], raw["metadatas"])
        ]
        return sorted(docs, key=lambda d: int(d.metadata.get("chunk_index", 0)))

    def similarity_search(self, doc_id: str, query: str, *, k: int) -> list[Document]:
        k = min(k, self.count(doc_id))
        return self.store(doc_id).similarity_search(query, k=k) if k > 0 else []

    def mmr_search(self, doc_id: str, query: str, *, k: int, fetch_k: int, lambda_mult: float) -> list[Document]:
        store = self.store(doc_id)
        fetch_k = max(k, min(fetch_k, self.count(doc_id)))
        if fetch_k == 0:
            return []
        return store.max_marginal_relevance_search(
            query, k=min(k, fetch_k), fetch_k=fetch_k, lambda_mult=lambda_mult
        )
