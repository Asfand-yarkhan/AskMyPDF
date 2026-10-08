# AskMyPDF

Upload PDFs, then chat with them. You get grounded answers with page citations (hover to preview the passage, click to open the page), summaries, study notes, interactive quizzes and spaced-repetition flashcards. Every answer comes strictly from your documents, in English, Urdu or Roman Urdu.

**Stack:** FastAPI · LangChain (LCEL) · ChromaDB · BM25 · cross-encoder reranking · PyMuPDF · sentence-transformers · Groq / OpenAI / Gemini · React 18 · Vite · TypeScript · Tailwind · shadcn/ui · Framer Motion · Zustand

---

## Quick start

### Option A: Docker

```bash
cp backend/.env.example backend/.env      # then add your GROQ_API_KEY (or another provider's key)
docker compose up --build
```

Open **http://localhost:8080**. The API is at http://localhost:8000 (interactive docs at `/docs`).
The backend image already contains Tesseract OCR and both AI models, so containers start without downloads.
Your documents, index and answer cache live in the `askmypdf-data` volume and survive restarts.

### Option B: Local dev

**Backend** (Python 3.11)

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements.txt
cp .env.example .env                    # add an API key
uvicorn app.main:app --reload --port 8000
```

The first start downloads the embedding and reranker models (~470 MB each).

**Frontend** (Node 20+)

```bash
cd frontend
npm install
npm run dev                             # http://localhost:5173 (proxies /api -> :8000)
```

**OCR (optional for local dev):** scanned PDFs need the Tesseract binary.
- Windows: install it from https://github.com/UB-Mannheim/tesseract/wiki, and set `TESSERACT_CMD` in `.env` if it isn't on PATH.
- macOS: `brew install tesseract`
- Debian/Ubuntu: `apt install tesseract-ocr`

---

## Testing and evaluation

```bash
cd backend && pytest                    # 65 unit tests (chunking, router, retrieval, cache, quiz schema)
cd frontend && npm test                 # 16 unit tests (citations, SSE parser, spaced repetition, exports)
```

**Answer-quality evaluation:** 18 questions over two synthetic PDFs (an employee handbook full of policy codes, and a
student result card whose semesters spill across pages), including Roman Urdu questions and questions the documents
can't answer, which must get "not found".

```bash
cd backend
python -m eval.make_fixtures            # generates eval/fixtures/*.pdf
python -m eval.run                      # production settings
python -m eval.run --retrieval-only     # force top-k search even for small documents
python -m eval.run --min-accuracy 0.9   # exit code 1 below 90% (CI gate)
```

It reports **answer accuracy** (every expected value present, or "not found" for unanswerable questions),
**retrieval hit rate** (the right page among the sources) and **latency**. It needs an LLM key and uses its own
data folder (`eval/.work`), so your documents are untouched.

**CI:** `.github/workflows/ci.yml` runs both test suites, the type-check and the production build on every push and
pull request. With Docker Hub secrets configured it also builds and pushes both images (see below).

---

## Docker images and Docker Hub

Building and running locally needs **no credentials**: `docker compose up --build`.

To publish the images to Docker Hub:

1. Create a free account at https://hub.docker.com.
2. Create an access token: **Account settings → Personal access tokens → Generate new token** with *Read & Write*
   scope. Use it instead of your password; it can be revoked at any time.
3. Log in once on your machine (the token is stored by Docker Desktop's credential helper, not in this project):
   ```bash
   docker login -u <your-dockerhub-username>      # paste the token when asked for a password
   ```
4. Build, tag and push:
   ```bash
   DOCKER_NAMESPACE=<your-dockerhub-username> TAG=1.0.0 docker compose build
   DOCKER_NAMESPACE=<your-dockerhub-username> TAG=1.0.0 docker compose push
   ```
   PowerShell: `$env:DOCKER_NAMESPACE="<user>"; $env:TAG="1.0.0"; docker compose build; docker compose push`

**Automatic publishing from GitHub:** in the repository go to **Settings → Secrets and variables → Actions** and add
`DOCKERHUB_USERNAME` (your username) and `DOCKERHUB_TOKEN` (the access token). Every push to `main` then publishes
`<user>/askmypdf-backend` and `<user>/askmypdf-frontend` tagged `latest` and with the branch or tag name.

API keys are never baked into images: the backend reads `backend/.env` at runtime (`env_file` in
`docker-compose.yml`), and `.env` is excluded by `.dockerignore`. On a hosting platform, set the same variables in
its dashboard.

---

## Configuration (`backend/.env`)

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq`, `openai` or `gemini` |
| `LLM_MODEL` / `ROUTER_MODEL` | per provider | Groq: `openai/gpt-oss-120b` / `openai/gpt-oss-20b` |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` | (none) | only the selected provider's key is needed |
| `OPENAI_BASE_URL` | (none) | any OpenAI-compatible server, e.g. Ollama `http://localhost:11434/v1` |
| `REASONING_EFFORT` | `high` | gpt-oss models: `low` / `medium` / `high` |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | multilingual; changing it re-indexes documents at startup |
| `RERANKER_MODEL` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | empty string disables reranking |
| `RETRIEVAL_K` / `RETRIEVAL_FETCH_K` / `RERANK_CANDIDATES` | `5` / `20` / `20` | passages to the LLM / per-method candidates / reranked pool |
| `FULL_CONTEXT_MAX_CHARS` | `14000` | documents this small are read in full instead of searched |
| `SUMMARY_MAX_INPUT_CHARS` | `24000` | fits Groq's free tier (8k tokens/min); raise on paid plans |
| `LLM_MAX_RETRIES` | `6` | waits for the provider's `retry-after` on rate limits |
| `CACHE_ENABLED` / `CACHE_TTL_HOURS` | `true` / `168` | answer cache for summaries, notes and first questions |
| `MAX_UPLOAD_MB` / `MAX_PAGES` | `50` / `100` | upload limits |
| `OCR_ENABLED`, `OCR_LANGUAGE`, `TESSERACT_CMD` | `true`, `eng` | use `eng+urd` for Urdu scans |
| `HF_TOKEN` | (none) | optional Hugging Face token for faster model downloads |

---

## How it works

```
PDF -> loader    PyMuPDF: pages, headings (font size / bold), tables -> markdown,
                 header/footer removal, OCR fallback for scanned pages
    -> analyzer  pages, words/page, heading density, table ratio, bullet ratio, technical signals, scanned?
    -> adaptive chunk config -> chunker -> Chroma collection "doc_<sha256>"   (skipped if hash already indexed)

Message -> intent router (small LLM -> JSON, regex fallback)
        -> QA | EXPLAIN | SUMMARY | NOTES | QUIZ | FLASHCARDS | OUT_OF_SCOPE
        -> answer cache (summaries, notes, first questions)

Retrieval: query rewrite (keeps your language + English translation)
        -> BM25 keyword search  ┐
        -> vector search (e5)   ┴> reciprocal rank fusion -> cross-encoder rerank -> top 5 -> LLM
```

### Retrieval

- **Hybrid search.** Embeddings capture meaning ("salary" ≈ "compensation") but blur exact tokens such as course codes,
  IDs or clause numbers ("CSC336", "POL-104"). BM25 keyword search finds those exactly. The two rankings are merged
  with reciprocal rank fusion.
- **Reranking.** A multilingual cross-encoder reads each (question, passage) pair together and re-orders the top 20
  candidates, giving a much sharper top 5.
- **Multilingual.** `multilingual-e5-small` embeds English, Urdu and Roman Urdu into one space; the query rewrite adds
  an English translation so keyword search matches English documents too.
- **Small documents** (under ~14k characters) skip retrieval and are read in full, which is most reliable for
  "last", "total" and "compare" questions.
- **Multiple documents.** Q&A and Explain can search up to 5 documents at once; citations then name the document,
  e.g. `[Doc 2, p. 4]`.

### Adaptive chunking

| Detected type | Rule | Size / overlap |
|---|---|---|
| Slides | 3+ pages and < 120 words/page | 1 slide = 1 chunk, overlap 0 |
| Notes | ≥ 35% of lines are list items | 600 / 120 |
| Short | < 10 pages | 600 / 120 (1000 / 160 if it has tables) |
| Technical / legal / research | ≥ 5 technical signals (abstract, et al., clause, theorem, ...) | 1200 / 200, or 1500 / 250 for dense pages |
| General report / book | otherwise | 1000 / 160-200 |
| Tables | always | kept whole with their caption and totals (very large tables split by rows, header repeated) |

Splitting follows the hierarchy **section (heading) → paragraph → line → sentence → clause → word → character**, so
chunks end at sentence boundaries. Each chunk stores `doc_id, chunk_id, chunk_index, page, page_end, page_breaks,
section, kind, has_table, filename`.

### Intents

- **QA / EXPLAIN**: hybrid retrieval (or the whole document if small), then a streamed answer with page citations.
  If the documents lack the answer: *"Ye information document mein nahi mili."*
- **SUMMARY / NOTES**: map-reduce within a token budget. Long documents use every section's opening plus passages
  spread evenly across the text. Styles: short, detailed, bullet (key points), notes.
- **QUIZ**: questions generated in parallel batches from passages across the document (or a topic), each validated
  with Pydantic; wrong-type or invalid items are dropped and topped up. Easy/medium/hard; mcq/true_false/short/mixed.
- **FLASHCARDS**: validated `{front, back, page}` cards.

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | multipart `file`. Streams SSE progress (`progress` events, then `complete` or `error`); `?stream=false` returns JSON |
| `GET` | `/documents` | list indexed documents with their chunk config and profile |
| `GET` | `/documents/{id}` | one document |
| `GET` | `/documents/{id}/file` | the original PDF (opened by citation chips) |
| `DELETE` | `/documents/{id}` | delete vectors, file, metadata and cached answers |
| `POST` | `/chat` | `{doc_id, extra_doc_ids?, message, history}` → SSE: `intent`, `status`, `sources`, `token`, `quiz`, `flashcards`, `cached`, `error`, `done` |
| `POST` | `/quiz/grade` | `{items:[{question,type,options,correct_answer,user_answer}]}` → score per item; short answers graded by the LLM |
| `GET` | `/health` | provider, models, key configured, document count, upload limits |

```bash
curl -F "file=@paper.pdf" "http://localhost:8000/upload?stream=false"
curl -N -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"doc_id":"<id>","extra_doc_ids":["<other id>"],"message":"Compare the refund policies","history":[]}'
```

---

## Frontend features

- Dark/light mode with one calm indigo → cyan theme.
- Drag-and-drop upload with real progress through *uploading → parsing → chunking → embedding*.
- Two-pane layout (documents, chat); the sidebar becomes a drawer on mobile.
- Streaming markdown with copy button, typing indicator and live status.
- **Citation chips**: hover to preview the exact passage used, click to open the PDF at that page.
- **Multi-document chat**: the "Search in" button picks extra documents to search together.
- **Instant answers**: repeated summaries and questions come from the cache (⚡ badge).
- Quick actions plus a quiz options popover (count, difficulty, type, topic).
- Quiz: one question at a time, instant feedback, explanations, score ring, confetti, "retry wrong ones",
  and **print / save as PDF** with an answer key.
- Flashcards: 3D flip, **spaced repetition** (Again / Good / Easy, "Due" review mode, progress kept in the
  browser) and **export** to Anki, CSV or print/PDF.
- Skeleton loaders, toasts, empty states, keyboard shortcuts (`?` lists them).

---

## Example queries to try

1. `What is the main conclusion of this document?` (QA with citations)
2. `Is document mein methodology kya hai?` (Roman Urdu, answered in Roman Urdu)
3. `What does it say about the moon landing in 1969?` (should reply "Ye information document mein nahi mili.")
4. `What does CSC336 / POL-104 / FR02-01 refer to?` (exact codes: keyword search)
5. `Summarize this document`, then ask again (second time is instant from the cache)
6. `List the key points of chapter 2` (bullet summary restricted to a topic)
7. `Generate a quiz` (10 medium MCQs), then **Print / PDF**
8. `Make 12 flashcards for revision`, grade them, then switch to **Due**
9. Select a second document with **Search in**, then ask `Compare the two documents`
10. `Explain <a concept> in simple words`, then follow up with `Give an example from the document`

---

## Project structure

```
backend/
  app/
    main.py              FastAPI routes, SSE, upload validation
    config.py            settings from .env
    schemas.py           Pydantic models (API, router, quiz)
    llm.py               provider factory (Groq / OpenAI / Gemini), rate-limit retries
    router.py            intent router (LLM JSON + heuristic fallback)
    orchestrator.py      route -> chain dispatch, answer cache, event stream
    retrieval.py         hybrid BM25 + vector search, RRF fusion, cross-encoder reranker
    vectorstore.py       Chroma (one collection per document) + embeddings
    cache.py             SQLite answer cache
    registry.py          document metadata (JSON file)
    ingestion/  loader.py  analyzer.py  chunker.py  pipeline.py
    chains/     common.py  qa.py  summary.py  quiz.py  study.py
  eval/         make_fixtures.py  dataset.jsonl  run.py
  tests/        chunker, router, retrieval, context, quiz schema, summary budget
frontend/
  src/
    api/         client.ts (fetch + SSE parser + XHR upload), types.ts
    store/       useAppStore.ts (zustand: chats, document scope, flashcard progress)
    hooks/       useChat, useUpload, useDocuments, useKeyboardShortcuts
    lib/         utils (citations), srs (spaced repetition), export (Anki/CSV/print)
    components/  ChatPanel, ChatMessage, CitationChip, DocumentScopePicker, QuizModal, FlashcardDeck, ...
    pages/       LandingPage, WorkspacePage
.github/workflows/ci.yml
docker-compose.yml
```
