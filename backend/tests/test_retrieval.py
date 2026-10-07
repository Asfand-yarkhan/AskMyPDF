"""Hybrid retrieval, rank fusion, response cache and multi-document citation tags."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from app.cache import ResponseCache, make_key, normalize_question
from app.chains.common import cite_tag, format_context
from app.config import Settings
from app.ingestion.chunker import Chunk
from app.retrieval import HybridRetriever, tokenize
from app.vectorstore import PrefixedEmbeddings, VectorStoreManager

TEXTS = [
    "Introduction to ICT covers computer basics and office tools.",
    "Programming Fundamentals teaches loops, functions and arrays in C++.",
    "CSC336 Web Technologies: grade F in Fall 2025, repeated in Spring 2026 with grade B.",
    "Linear Algebra covers matrices, vectors and eigenvalues.",
    "Islamic Studies and Pakistan Studies are compulsory humanities courses.",
]


def make_retriever(tmp_path, docs: dict[str, list[str]]) -> HybridRetriever:
    settings = Settings(data_dir=tmp_path, reranker_model="", retrieval_fetch_k=10)
    settings.ensure_dirs()
    store = VectorStoreManager(settings, embeddings=DeterministicFakeEmbedding(size=32))
    for doc_id, texts in docs.items():
        chunks = [
            Chunk(text=t, metadata={"doc_id": doc_id, "chunk_id": f"{doc_id}-{i}", "chunk_index": i,
                                    "page": i + 1, "page_end": i + 1, "section": "", "filename": f"{doc_id}.pdf"})
            for i, t in enumerate(texts)
        ]
        store.add_chunks(doc_id, chunks)
    return HybridRetriever(settings, store)


def test_tokenize_keeps_codes_and_urdu() -> None:
    assert tokenize("What is CSC336's grade?") == ["csc336", "s", "grade"]
    assert "خلاصہ" in tokenize("اس کا خلاصہ")


def test_keyword_search_finds_exact_code(tmp_path) -> None:
    retriever = make_retriever(tmp_path, {"aaaa1111": TEXTS})
    hits = retriever.keyword_search("aaaa1111", "CSC336", 3)
    assert hits and "CSC336" in hits[0].page_content


def test_hybrid_search_ranks_exact_match_first(tmp_path) -> None:
    # Fake embeddings are random, so only the BM25 half can find the code: fusion must surface it.
    retriever = make_retriever(tmp_path, {"aaaa1111": TEXTS})
    top = retriever.search(["aaaa1111"], "grade in CSC336", k=2)
    assert "CSC336" in top[0].page_content


def test_search_across_documents(tmp_path) -> None:
    retriever = make_retriever(tmp_path, {
        "aaaa1111": TEXTS,
        "bbbb2222": ["The refund policy POL-104 allows returns within 30 days.", "Shipping takes 5 days."],
    })
    top = retriever.search(["aaaa1111", "bbbb2222"], "POL-104 refund", k=3)
    assert top[0].metadata["doc_id"] == "bbbb2222"


def test_bm25_index_rebuilds_after_reingest(tmp_path) -> None:
    retriever = make_retriever(tmp_path, {"aaaa1111": TEXTS})
    assert retriever.keyword_search("aaaa1111", "kubernetes", 3) == []
    store = retriever.vectorstore
    store.delete("aaaa1111")
    store.add_chunks("aaaa1111", [Chunk(text="Kubernetes orchestrates containers.", metadata={
        "doc_id": "aaaa1111", "chunk_id": "aaaa1111-0", "chunk_index": 0, "page": 1, "page_end": 1,
        "section": "", "filename": "a.pdf"})])
    assert retriever.keyword_search("aaaa1111", "kubernetes", 3)


def test_rrf_fusion_rewards_agreement() -> None:
    a, b, c = (Document(page_content=x, metadata={"chunk_id": x}) for x in "abc")
    fused = HybridRetriever.fuse([[a, b, c], [b, c, a]])
    assert fused[0].metadata["chunk_id"] == "b"


def test_e5_prefixes() -> None:
    class Spy(DeterministicFakeEmbedding):
        seen: list[str] = []

        def embed_query(self, text: str) -> list[float]:
            self.seen.append(text)
            return super().embed_query(text)

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.seen.extend(texts)
            return super().embed_documents(texts)

    spy = Spy(size=8)
    emb = PrefixedEmbeddings(spy, query_prefix="query: ", document_prefix="passage: ")
    emb.embed_query("hello")
    emb.embed_documents(["world"])
    assert spy.seen == ["query: hello", "passage: world"]


def test_cache_roundtrip_and_forget(tmp_path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite", ttl_hours=1)
    key = make_key(doc="a", q=normalize_question("What is RAG?  "))
    assert key == make_key(doc="a", q=normalize_question("what is rag"))
    cache.put(key, ["aaaa1111", "bbbb2222"], [{"type": "token", "content": "hi"}])
    assert cache.get(key) == [{"type": "token", "content": "hi"}]
    assert cache.forget_document("bbbb2222") == 1
    assert cache.get(key) is None


def test_cache_expires(tmp_path) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite", ttl_hours=0)
    cache.put("k", ["a"], [{"type": "token", "content": "x"}])
    assert cache.get("k") is None


def test_multi_document_citation_tags() -> None:
    assert cite_tag(4) == "[p. 4]"
    assert cite_tag(4, 2) == "[Doc 2, p. 4]"
    doc = Document(page_content="text", metadata={"doc_id": "bbbb", "page": 3, "filename": "b.pdf"})
    assert format_context([doc], {"aaaa": 1, "bbbb": 2}).startswith("[Doc 2, p. 3]\n(file: b.pdf)")
    assert format_context([doc]).startswith("[p. 3]")
