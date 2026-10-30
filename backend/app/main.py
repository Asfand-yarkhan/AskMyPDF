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

from app.auth import (
    TokenVerifier,
    User,
    client_ip,
    current_user,
    load_or_create_secret,
    sign_file_token,
    user_from_claims,
    verify_file_token,
)
from app.chains import quiz as quiz_chain
from app.config import Settings, configure_logging, get_settings
from app.ingestion.loader import PDFParseError
from app.ingestion.pipeline import file_hash, ingest_pdf
from app.llm import LLMConfigError, llm_configured
from app.cache import ResponseCache
from app.orchestrator import ChatOrchestrator
from app.retrieval import HybridRetriever
from app.registry import DocumentRegistry
from app.schemas import (
    ChatRequest,
    ClaimRequest,
    DocumentInfo,
    DocumentView,
    GradeRequest,
    GradeResponse,
    HealthResponse,
    MeResponse,
)
from app.usage import TrialExhausted, UsageTracker
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
    app.state.retriever = HybridRetriever(settings, vectorstore)
    app.state.cache = ResponseCache(settings.cache_path, settings.cache_ttl_hours, settings.cache_enabled)
    app.state.orchestrator = ChatOrchestrator(settings, app.state.retriever, app.state.cache)
    app.state.verifier = TokenVerifier(settings.firebase_project_id) if settings.firebase_project_id else None
    app.state.usage = UsageTracker(settings.usage_path, settings.guest_trials, settings.guest_ip_trials_per_day)
    app.state.file_secret = load_or_create_secret(settings)
    logger.info(
        "AskMyPDF ready: llm=%s/%s configured=%s, reranker=%s, accounts=%s, %d documents",
        settings.llm_provider, settings.resolved_llm_model, llm_configured(),
        settings.reranker_model or "off", settings.firebase_project_id or "off (single local user)",
        len(app.state.registry.list()),
    )
    # Load the reranker and rebuild stale indexes in the background so startup stays fast.
    warm = asyncio.create_task(asyncio.to_thread(app.state.retriever.reranker.warm_up))
    reindex = asyncio.create_task(_reindex_stale_documents(app))
    yield
    reindex.cancel()
    warm.cancel()


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


app = FastAPI(title="AskMyPDF API", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_origin_regex=get_settings().cors_origin_regex or None,
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


def coded_error(status_code: int, code: str, message: str) -> HTTPException:
    """An error the frontend can act on (e.g. open the sign-up dialog), not just display."""
    return HTTPException(status_code, {"code": code, "message": message})


def owned_document(request: Request, user: User, doc_id: str) -> DocumentInfo:
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid document id.")
    registry: DocumentRegistry = request.app.state.registry
    doc = registry.get(doc_id)
    visible = doc is not None and (not request.app.state.settings.auth_enabled or registry.is_owner(doc_id, user.uid))
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found. Please upload it again.")
    return doc


def get_document(doc_id: str, request: Request, user: User = Depends(current_user)) -> DocumentInfo:
    return owned_document(request, user, doc_id)


def to_view(request: Request, doc: DocumentInfo) -> DocumentView:
    settings: Settings = request.app.state.settings
    token = sign_file_token(request.app.state.file_secret, doc.doc_id, settings.file_url_ttl_hours * 3600)
    return DocumentView(**doc.model_dump(), file_token=token)


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
        max_upload_mb=settings.max_upload_mb,
        max_pages=settings.max_pages,
        auth_enabled=settings.auth_enabled,
    )


@app.get("/me", response_model=MeResponse)
async def me(request: Request, user: User = Depends(current_user)) -> MeResponse:
    trial = request.app.state.usage.status(user, client_ip(request))
    return MeResponse(
        uid=user.uid,
        email=user.email,
        is_guest=user.is_guest,
        email_verified=user.email_verified,
        auth_enabled=request.app.state.settings.auth_enabled,
        trials_used=trial.used if trial else None,
        trials_limit=trial.limit if trial else None,
        trials_remaining=trial.remaining if trial else None,
    )


@app.post("/me/claim")
async def claim_guest_documents(
    body: ClaimRequest, request: Request, user: User = Depends(current_user)
) -> dict[str, int]:
    """After a guest signs in to an existing account, move the guest's documents to it."""
    verifier = request.app.state.verifier
    if verifier is None or user.is_guest:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sign in to an account first.")
    try:
        guest = user_from_claims(verifier.verify(body.guest_token))
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The guest session has expired.") from exc
    if not guest.is_guest:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only guest documents can be moved.")
    moved = request.app.state.registry.transfer_owner(guest.uid, user.uid)
    logger.info("Moved %d documents from guest %s to %s", moved, guest.uid, user.uid)
    return {"moved": moved}


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


def _check_document_limit(settings: Settings, registry: DocumentRegistry, user: User, data: bytes) -> None:
    if not settings.auth_enabled or registry.is_owner(file_hash(data), user.uid):
        return
    owned = len(registry.list(user.uid))
    if not user.is_member and owned >= settings.guest_max_documents:
        if not user.is_guest:
            raise coded_error(
                status.HTTP_403_FORBIDDEN, "email_unverified",
                "Verify your email address to upload more documents.",
            )
        raise coded_error(
            status.HTTP_403_FORBIDDEN, "signup_required",
            "Create a free account to upload more documents.",
        )
    if user.is_member and owned >= settings.user_max_documents:
        raise coded_error(
            status.HTTP_403_FORBIDDEN, "document_limit",
            f"You can keep up to {settings.user_max_documents} documents. Delete one to upload another.",
        )


@app.post("/upload", response_model=None)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    stream: bool = Query(True, description="Stream ingestion progress as Server-Sent Events"),
    settings: Settings = Depends(settings_dep),
    user: User = Depends(current_user),
) -> StreamingResponse | dict[str, Any]:
    registry: DocumentRegistry = request.app.state.registry
    data = await _read_upload(file, settings.max_upload_mb * 1024 * 1024)
    _check_document_limit(settings, registry, user, data)
    filename = re.sub(r"[^\w\-. ()]+", "_", file.filename or "document.pdf")[:200]
    kwargs = {"settings": settings, "vectorstore": request.app.state.vectorstore, "registry": registry}

    if not stream:
        try:
            info, reused = await asyncio.to_thread(ingest_pdf, data, filename, **kwargs)
        except PDFParseError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        registry.add_owner(info.doc_id, user.uid)
        return {"document": to_view(request, info).model_dump(mode="json"), "reused": reused}

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
            registry.add_owner(info.doc_id, user.uid)
            document = to_view(request, info).model_dump(mode="json")
            yield sse({"type": "complete", "document": document, "reused": reused})
        except PDFParseError as exc:
            yield sse({"type": "error", "message": str(exc)})
        except Exception:
            logger.exception("Ingestion failed for %s", filename)
            yield sse({"type": "error", "message": "Failed to process this PDF."})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/documents", response_model=list[DocumentView])
async def list_documents(
    request: Request, settings: Settings = Depends(settings_dep), user: User = Depends(current_user)
) -> list[DocumentView]:
    owner = user.uid if settings.auth_enabled else None
    return [to_view(request, d) for d in request.app.state.registry.list(owner)]


@app.get("/documents/{doc_id}", response_model=DocumentView)
async def document_detail(request: Request, doc: DocumentInfo = Depends(get_document)) -> DocumentView:
    return to_view(request, doc)


@app.get("/documents/{doc_id}/file")
async def document_file(
    doc_id: str,
    request: Request,
    token: str = Query("", description="Signed token from the document listing"),
    settings: Settings = Depends(settings_dep),
    registry: DocumentRegistry = Depends(registry_dep),
) -> FileResponse:
    # Opened in a new tab (no Authorization header), so access is proven by the signed token.
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid document id.")
    if settings.auth_enabled and not verify_file_token(request.app.state.file_secret, doc_id, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This link has expired. Reload AskMyPDF and try again.")
    doc = registry.get(doc_id)
    path = settings.upload_dir / f"{doc_id}.pdf"
    if doc is None or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF file is missing on the server.")
    return FileResponse(
        path, media_type="application/pdf", filename=doc.filename,
        content_disposition_type="inline",
    )


@app.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    request: Request,
    doc: DocumentInfo = Depends(get_document),
    user: User = Depends(current_user),
    registry: DocumentRegistry = Depends(registry_dep),
    vectorstore: VectorStoreManager = Depends(vectorstore_dep),
    settings: Settings = Depends(settings_dep),
) -> None:
    # Other users may have uploaded the same PDF; only the last owner's delete removes the files.
    if settings.auth_enabled and not registry.remove_owner(doc.doc_id, user.uid):
        logger.info("Removed %s from %s's documents; other owners keep it", doc.doc_id, user.uid)
        return
    await asyncio.to_thread(vectorstore.delete, doc.doc_id)
    (settings.upload_dir / f"{doc.doc_id}.pdf").unlink(missing_ok=True)
    registry.remove(doc.doc_id)
    dropped = request.app.state.cache.forget_document(doc.doc_id)
    logger.info("Deleted document %s (%s), %d cached answers", doc.filename, doc.doc_id, dropped)


@app.post("/chat")
async def chat(request: Request, body: ChatRequest, user: User = Depends(current_user)) -> StreamingResponse:
    doc = owned_document(request, user, body.doc_id)
    extras = [owned_document(request, user, i) for i in dict.fromkeys(body.extra_doc_ids) if i != doc.doc_id]
    try:
        trial = request.app.state.usage.consume(user, client_ip(request))
    except TrialExhausted as exc:
        if not user.is_guest:  # signed up, but hasn't clicked the email link yet
            raise coded_error(
                status.HTTP_403_FORBIDDEN, "email_unverified",
                "Verify your email address to keep going. Check your inbox for the link.",
            ) from exc
        raise coded_error(
            status.HTTP_403_FORBIDDEN, "trial_exhausted",
            f"You have used your {exc.status.limit} free questions. Create a free account to keep going.",
        ) from exc
    orchestrator: ChatOrchestrator = request.app.state.orchestrator

    async def events() -> AsyncIterator[str]:
        if trial is not None:
            yield sse({"type": "usage", "trials_remaining": trial.remaining, "trials_limit": trial.limit})
        async for event in orchestrator.stream(body, [doc, *extras]):
            if await request.is_disconnected():
                logger.info("Client disconnected; stopping generation")
                break
            yield sse(event)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/quiz/grade", response_model=GradeResponse)
async def grade_quiz(body: GradeRequest, _: User = Depends(current_user)) -> GradeResponse:
    return await quiz_chain.grade(body.items)
