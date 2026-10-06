"""ChromaDB persistence: one collection per document (keyed by file hash)."""

from __future__ import annotations

import logging
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


def build_embeddings(settings: Settings) -> Embeddings:
    provider = settings.embedding_provider
    if provider == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name=settings.embedding_model,
            model_kwargs={"device": settings.embedding_device},
            encode_kwargs={"normalize_embeddings": True},
        )
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
        logger.info("Embedded %d chunks for %s", total, doc_id)

    def delete(self, doc_id: str) -> None:
        with self._lock:
            self._stores.pop(doc_id, None)
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

    def mmr_search(self, doc_id: str, query: str, *, k: int, fetch_k: int, lambda_mult: float) -> list[Document]:
        store = self.store(doc_id)
        fetch_k = max(k, min(fetch_k, self.count(doc_id)))
        if fetch_k == 0:
            return []
        return store.max_marginal_relevance_search(
            query, k=min(k, fetch_k), fetch_k=fetch_k, lambda_mult=lambda_mult
        )
