"""AskMyPDF FastAPI application."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.chains import quiz as quiz_chain
from app.config import Settings, configure_logging, get_settings
from app.ingestion.loader import PDFParseError
from app.ingestion.pipeline import ingest_pdf
from app.llm import LLMConfigError, llm_configured
from app.orchestrator import ChatOrchestrator
from app.registry import DocumentRegistry
from app.schemas import ChatRequest, DocumentInfo, GradeRequest, GradeResponse, HealthResponse
from app.vectorstore import VectorStoreManager

logger = logging.getLogger("askmypdf")

PDF_MIME_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream", ""}
DOC_ID_RE = re.compile(r"^[a-f0-9]{8,64}$")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_dirs()
    logger.info("Loading embeddings (%s)...", settings.embedding_id)
    vectorstore = await asyncio.to_thread(VectorStoreManager, settings)
    app.state.settings = settings
    app.state.vectorstore = vectorstore
    app.state.registry = DocumentRegistry(settings.registry_path)
    app.state.orchestrator = ChatOrchestrator(settings, vectorstore)
    logger.info(
        "AskMyPDF ready: llm=%s/%s configured=%s, %d documents",
        settings.llm_provider, settings.resolved_llm_model, llm_configured(), len(app.state.registry.list()),
    )
    reindex = asyncio.create_task(_reindex_stale_documents(app))
    yield
    reindex.cancel()


async def _reindex_stale_documents(app: FastAPI) -> None:
    """Rebuild indexes created by an older chunker or embedding model, from the saved PDFs."""
    settings: Settings = app.state.settings
    registry: DocumentRegistry = app.state.registry
    for doc in registry.list():
        if doc.embedding_id == settings.embedding_id:
            continue
        path = settings.upload_dir / f"{doc.doc_id}.pdf"
        if not path.exists():
            logger.warning("Cannot re-index %s: PDF missing", doc.filename)
            continue
        logger.info("Re-indexing %s (%s -> %s)", doc.filename, doc.embedding_id, settings.embedding_id)
        try:
            await asyncio.to_thread(
                ingest_pdf, path.read_bytes(), doc.filename,
                settings=settings, vectorstore=app.state.vectorstore, registry=registry,
            )
        except Exception:
            logger.exception("Re-indexing %s failed", doc.filename)


app = FastAPI(title="AskMyPDF API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Dependencies & errors ------------------------------------------------------


def settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def registry_dep(request: Request) -> DocumentRegistry:
    return request.app.state.registry


def vectorstore_dep(request: Request) -> VectorStoreManager:
    return request.app.state.vectorstore


def get_document(doc_id: str, registry: DocumentRegistry = Depends(registry_dep)) -> DocumentInfo:
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid document id.")
    doc = registry.get(doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found. Please upload it again.")
    return doc


@app.exception_handler(LLMConfigError)
async def llm_config_handler(_: Request, exc: LLMConfigError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


def sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


# --- Routes ----------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(settings_dep), registry: DocumentRegistry = Depends(registry_dep)
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        llm_provider=settings.llm_provider,
        llm_model=settings.resolved_llm_model,
        router_model=settings.resolved_router_model,
        embedding_model=settings.embedding_model,
        llm_configured=llm_configured(),
        documents=len(registry.list()),
    )


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    name = file.filename or ""
    if not name.lower().endswith(".pdf") or (file.content_type or "") not in PDF_MIME_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are supported.")
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds {max_bytes // (1024 * 1024)} MB limit."
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "This file is not a valid PDF.")
    return data


@app.post("/upload", response_model=None)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    stream: bool = Query(True, description="Stream ingestion progress as Server-Sent Events"),
    settings: Settings = Depends(settings_dep),
) -> StreamingResponse | dict[str, Any]:
    data = await _read_upload(file, settings.max_upload_mb * 1024 * 1024)
    filename = re.sub(r"[^\w\-. ()]+", "_", file.filename or "document.pdf")[:200]
    kwargs = {
        "settings": settings,
        "vectorstore": request.app.state.vectorstore,
        "registry": request.app.state.registry,
    }

    if not stream:
        try:
            info, reused = await asyncio.to_thread(ingest_pdf, data, filename, **kwargs)
        except PDFParseError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"document": info.model_dump(mode="json"), "reused": reused}

    async def events() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def progress(stage: str, value: float, message: str) -> None:
            event = {"type": "progress", "stage": stage, "progress": round(value, 3), "message": message}
            loop.call_soon_threadsafe(queue.put_nowait, event)

        task = asyncio.ensure_future(asyncio.to_thread(ingest_pdf, data, filename, progress=progress, **kwargs))
        yield sse({"type": "progress", "stage": "uploaded", "progress": 0.0, "message": "Upload received"})
        while not task.done():
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                yield sse(getter.result())
            else:
                getter.cancel()
        while not queue.empty():
            yield sse(queue.get_nowait())
        try:
            info, reused = task.result()
            yield sse({"type": "complete", "document": info.model_dump(mode="json"), "reused": reused})
        except PDFParseError as exc:
            yield sse({"type": "error", "message": str(exc)})
        except Exception:
            logger.exception("Ingestion failed for %s", filename)
            yield sse({"type": "error", "message": "Failed to process this PDF."})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/documents", response_model=list[DocumentInfo])
async def list_documents(registry: DocumentRegistry = Depends(registry_dep)) -> list[DocumentInfo]:
    return registry.list()


@app.get("/documents/{doc_id}", response_model=DocumentInfo)
async def document_detail(doc: DocumentInfo = Depends(get_document)) -> DocumentInfo:
    return doc


@app.get("/documents/{doc_id}/file")
async def document_file(
    doc: DocumentInfo = Depends(get_document), settings: Settings = Depends(settings_dep)
) -> FileResponse:
    path = settings.upload_dir / f"{doc.doc_id}.pdf"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF file is missing on the server.")
    return FileResponse(
        path, media_type="application/pdf", filename=doc.filename,
        content_disposition_type="inline",
    )


@app.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc: DocumentInfo = Depends(get_document),
    registry: DocumentRegistry = Depends(registry_dep),
    vectorstore: VectorStoreManager = Depends(vectorstore_dep),
    settings: Settings = Depends(settings_dep),
) -> None:
    await asyncio.to_thread(vectorstore.delete, doc.doc_id)
    (settings.upload_dir / f"{doc.doc_id}.pdf").unlink(missing_ok=True)
    registry.remove(doc.doc_id)
    logger.info("Deleted document %s (%s)", doc.filename, doc.doc_id)


@app.post("/chat")
async def chat(request: Request, body: ChatRequest, registry: DocumentRegistry = Depends(registry_dep)) -> StreamingResponse:
    doc = get_document(body.doc_id, registry)
    orchestrator: ChatOrchestrator = request.app.state.orchestrator

    async def events() -> AsyncIterator[str]:
        async for event in orchestrator.stream(body, doc):
            if await request.is_disconnected():
                logger.info("Client disconnected; stopping generation")
                break
            yield sse(event)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/quiz/grade", response_model=GradeResponse)
async def grade_quiz(body: GradeRequest) -> GradeResponse:
    return await quiz_chain.grade(body.items)
