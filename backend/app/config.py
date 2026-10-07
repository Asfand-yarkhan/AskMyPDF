"""Application settings loaded from environment / .env (never hardcode keys)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
CHUNKER_VERSION = "chunker-v4"  # bump when chunking/metadata changes so old indexes are rebuilt

LLMProvider = Literal["groq", "openai", "gemini"]
EmbeddingProvider = Literal["huggingface", "openai", "gemini"]

DEFAULT_LLM_MODELS: dict[str, str] = {
    "groq": "openai/gpt-oss-120b",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}
DEFAULT_ROUTER_MODELS: dict[str, str] = {
    "groq": "openai/gpt-oss-20b",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash-lite",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AskMyPDF"
    log_level: str = "INFO"

    # --- LLM -----------------------------------------------------------------
    llm_provider: LLMProvider = "groq"
    llm_model: str | None = None
    router_model: str | None = None
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None  # any OpenAI-compatible server (e.g. Ollama)
    google_api_key: SecretStr | None = None
    reasoning_effort: Literal["low", "medium", "high"] = "high"  # gpt-oss models only
    qa_temperature: float = 0.0
    quiz_temperature: float = 0.4
    llm_timeout_s: float = 90.0
    llm_max_retries: int = 6  # retries (with the provider's retry-after wait) on rate limits / errors

    # --- Embeddings ------------------------------------------------------------
    embedding_provider: EmbeddingProvider = "huggingface"
    # Multilingual (English, Urdu, Roman Urdu, 90+ languages); e5 query/passage prefixes are added automatically.
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_device: str = "cpu"
    hf_token: SecretStr | None = None  # optional: higher Hugging Face Hub rate limits

    # --- Storage -------------------------------------------------------------
    data_dir: Path = BACKEND_DIR / "data"
    max_upload_mb: int = 50
    max_pages: int = 100

    # --- Retrieval / generation -------------------------------------------------
    retrieval_k: int = 5
    retrieval_fetch_k: int = 20  # candidates per search method (vector and BM25) before fusion
    mmr_lambda: float = 0.6
    # Cross-encoder that re-scores fused candidates; empty string disables reranking.
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    rerank_candidates: int = 20

    # Cache for summaries/notes and history-free questions (SQLite in DATA_DIR).
    cache_enabled: bool = True
    cache_ttl_hours: int = 168
    # Documents up to this many characters are given to the QA model in full instead of top-k chunks.
    full_context_max_chars: int = 14_000
    max_history_turns: int = 6
    map_concurrency: int = 3
    # Summaries/notes read at most this much text (~4 chars per token). The default fits Groq's
    # free tier (8k tokens/min per model); raise it on paid plans for fuller coverage of long PDFs.
    summary_max_input_chars: int = 24_000
    summary_group_chars: int = 12_000
    not_found_message: str = "Ye information document mein nahi mili."

    # --- OCR -----------------------------------------------------------------
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    tesseract_cmd: str | None = None

    # --- HTTP ----------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cache_path(self) -> Path:
        return self.data_dir / "cache.sqlite"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "documents.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_LLM_MODELS[self.llm_provider]

    @property
    def resolved_router_model(self) -> str:
        return self.router_model or DEFAULT_ROUTER_MODELS[self.llm_provider]

    @property
    def embedding_id(self) -> str:
        """Identifies the index format (embedding space + chunker); stale documents get re-ingested."""
        return f"{self.embedding_provider}:{self.embedding_model}|{CHUNKER_VERSION}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.chroma_dir, self.upload_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party libraries are chatty at INFO.
    for noisy in ("httpx", "chromadb", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
