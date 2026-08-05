import os
import re
import uuid
import io
from typing import Dict, List, Optional

import requests
import streamlit as st
import pdfplumber
from dotenv import load_dotenv

load_dotenv()

# Ollama runs locally — no internet, no API key, no quota issues
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

st.set_page_config(page_title="AskMyPDF", page_icon="⚡", layout="wide")

PROMPT_TEMPLATE = """You are AskMyPDF, a precise document question-answering assistant.

STRICT RULES (follow ALL of these exactly):
1. Answer ONLY using facts explicitly stated in the DOCUMENT CONTEXT below.
2. If the answer is not in the context, say exactly: "This information is not available in the provided document."
3. DO NOT invent, guess, or extrapolate any facts, dates, numbers, names, or values.
4. When citing numbers, marks, dates, semesters — copy them EXACTLY as written in the context.
5. Keep answers concise and factual. Use bullet points for lists.
6. Respond in the SAME language as the question (if Urdu/Roman-Urdu → reply in Roman Urdu).
7. Tables are formatted as markdown — read row and column headers carefully before answering.

DOCUMENT CONTEXT:
---
{context}
---

CHAT HISTORY (for follow-up context):
{chat_history}

Question: {question}
Answer:"""

STOPWORDS = {
    "the", "is", "at", "which", "on", "a", "an", "and", "or", "but",
    "in", "with", "to", "of", "for", "from", "by", "this", "that",
    "was", "are", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "shall", "should", "may",
    "might", "must", "can", "could", "not", "no", "so", "it",
    "its", "i", "we", "you", "he", "she", "they", "my", "our",
    "your", "his", "her", "their", "me", "us", "him", "them",
    "what", "when", "where", "who", "how", "why", "if", "as",
    "then", "than", "about", "into", "through", "during", "before",
    "after", "above", "below", "up", "down", "out", "off",
}


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]{3,}", text.lower())


def filter_tokens(tokens: List[str]) -> List[str]:
    return [token for token in tokens if token not in STOPWORDS]


def bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    avg_doc_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    doc_len = len(doc_tokens)
    freq: Dict[str, int] = {}
    for token in doc_tokens:
        freq[token] = freq.get(token, 0) + 1

    score = 0.0
    for qt in query_tokens:
        tf = freq.get(qt, 0)
        if tf == 0:
            continue
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * (doc_len / max(avg_doc_length, 1)))
        score += numerator / denominator
    return score


def ngram_similarity(query: str, doc: str, n: int = 3) -> float:
    q = query.lower()
    d = doc.lower()
    q_ngrams = {q[i: i + n] for i in range(max(len(q) - n + 1, 0))}
    d_ngrams = {d[i: i + n] for i in range(max(len(d) - n + 1, 0))}
    if not q_ngrams or not d_ngrams:
        return 0.0
    intersection = len(q_ngrams & d_ngrams)
    union = len(q_ngrams | d_ngrams)
    return intersection / max(union, 1)


def reciprocal_rank_fusion(ranked_lists: List[List[Dict]], k: int = 60) -> List[Dict]:
    score_map: Dict[int, Dict] = {}
    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list):
            key = chunk["chunk_index"]
            rrf_score = 1.0 / (k + rank + 1)
            if key in score_map:
                score_map[key]["rrf"] += rrf_score
            else:
                score_map[key] = {"chunk": chunk, "rrf": rrf_score}
    fused = sorted(score_map.values(), key=lambda item: item["rrf"], reverse=True)
    return [item["chunk"] for item in fused]


def hybrid_retrieve(query: str, chunks: List[Dict], top_k: int = 5) -> List[Dict]:
    if not chunks:
        return []
    query_tokens = filter_tokens(tokenize(query))
    chunk_docs = [filter_tokens(tokenize(chunk["content"])) for chunk in chunks]
    avg_len = sum(len(doc) for doc in chunk_docs) / max(len(chunk_docs), 1)

    bm25_ranked = []
    ngram_ranked = []
    for chunk, doc_tokens in zip(chunks, chunk_docs):
        bm25_ranked.append({**chunk, "score": bm25_score(query_tokens, doc_tokens, avg_len)})
        ngram_ranked.append({**chunk, "score": ngram_similarity(query, chunk["content"])})

    bm25_ranked.sort(key=lambda item: item["score"], reverse=True)
    ngram_ranked.sort(key=lambda item: item["score"], reverse=True)
    fused = reciprocal_rank_fusion([bm25_ranked, ngram_ranked])
    return fused[:top_k]


def build_prompt(context: str, chat_history: str, question: str) -> str:
    return PROMPT_TEMPLATE.format(
        context=context,
        chat_history=chat_history or "No previous conversation.",
        question=question,
    )


def table_to_markdown(table: List[List[Optional[str]]]) -> str:
    """Convert a pdfplumber table (list of rows) to a clean markdown table string."""
    if not table:
        return ""
    # Replace None cells with empty string
    rows = [[cell if cell is not None else "" for cell in row] for row in table]
    # Use first row as header
    header = rows[0]
    separator = ["---"] * len(header)
    body = rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        # Pad row if shorter than header
        while len(row) < len(header):
            row.append("")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def extract_pdf_text(uploaded_file) -> str:
    """
    Extract text and tables from a PDF using pdfplumber.
    Tables are converted to markdown format for better LLM comprehension.
    Returns pages joined by form-feed characters.
    """
    file_bytes = uploaded_file.read()
    pages_text = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            parts = []

            # Extract tables first and track their bounding boxes
            tables = page.extract_tables()
            table_bboxes = []
            for table in tables:
                # Find table bbox to exclude from plain text extraction
                table_settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
                try:
                    for t in page.find_tables(table_settings):
                        table_bboxes.append(t.bbox)
                except Exception:
                    pass
                md_table = table_to_markdown(table)
                if md_table:
                    parts.append(f"\n[TABLE]\n{md_table}\n[/TABLE]\n")

            # Extract plain text (words not inside table bboxes)
            plain_text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if plain_text:
                parts.append(plain_text)

            page_content = "\n".join(parts).strip()
            if page_content:
                pages_text.append(page_content)

    return "\n\f\n".join(pages_text)


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> List[str]:
    # Keep table blocks intact — don't split inside [TABLE]...[/TABLE]
    segments = re.split(r"(\[TABLE\].*?\[/TABLE\])", text, flags=re.DOTALL)
    chunks: List[str] = []
    current = ""

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        # Table blocks are always kept as a single chunk
        if segment.startswith("[TABLE]"):
            if current and len(current) > 40:
                chunks.append(current.strip())
                current = ""
            chunks.append(segment)
            continue
        # Split normal text by sentences
        sentences = re.split(r"(?<=[.!?])\s+|\n\n+", segment)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(current) + len(sentence) + 1 > chunk_size and current:
                chunks.append(current.strip())
                current = (current[-overlap:] + " " + sentence).strip()
            else:
                current = f"{current} {sentence}".strip() if current else sentence

    if current and len(current) > 40:
        chunks.append(current.strip())
    return chunks


def build_chunks(pdf_text: str) -> List[Dict]:
    pages = pdf_text.split("\f")
    chunks: List[Dict] = []
    chunk_idx = 0
    for page_num, page_text in enumerate(pages, start=1):
        page_text = page_text.strip()
        if not page_text:
            continue
        for chunk in chunk_text(page_text):
            chunks.append(
                {
                    "content": chunk,
                    "page": page_num,
                    "chunk_index": chunk_idx,
                    "is_table": chunk.startswith("[TABLE]"),
                }
            )
            chunk_idx += 1
    return chunks


def check_ollama() -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return any(OLLAMA_MODEL in m for m in models)
        return False
    except Exception:
        return False


def query_ollama(prompt: str) -> str:
    """Call local Ollama API — no internet, no API key required."""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "num_predict": 900,
                    "repeat_penalty": 1.05,
                },
            },
            timeout=180,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "❌ Cannot connect to Ollama.\n\n"
            "**Steps to fix:**\n"
            "1. Download Ollama from https://ollama.com/download\n"
            "2. Install and open it (it runs in the system tray)\n"
            f"3. Run: `ollama pull {OLLAMA_MODEL}`\n"
            "4. Refresh this page"
        )


def initialize_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "chunks" not in st.session_state:
        st.session_state.chunks = []
    if "pdf_name" not in st.session_state:
        st.session_state.pdf_name = ""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "top_k" not in st.session_state:
        st.session_state.top_k = 5
    if "total_pages" not in st.session_state:
        st.session_state.total_pages = 0
    if "total_chunks" not in st.session_state:
        st.session_state.total_chunks = 0
    if "table_count" not in st.session_state:
        st.session_state.table_count = 0


def reset_session() -> None:
    st.session_state.messages = []
    st.session_state.chunks = []
    st.session_state.pdf_name = ""
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.total_pages = 0
    st.session_state.total_chunks = 0
    st.session_state.table_count = 0


def display_message(message: Dict) -> None:
    role = message.get("role")
    content = message.get("content", "")
    sources = message.get("sources")
    with st.chat_message(role):
        st.markdown(content)
        if sources:
            with st.expander("Show retrieved source chunks", expanded=False):
                for src in sources:
                    tag = "📊 TABLE" if src.get("is_table") else "📄 Text"
                    st.markdown(
                        f"- {tag} · Page {src['page']} · Chunk {src['chunk_index'] + 1} · Score {src.get('score', 0):.4f}\n\n"
                        f"{src['content']}"
                    )


def main() -> None:
    initialize_state()

    st.title("⚡ AskMyPDF — Intelligent Document Q&A")
    st.write(
        f"Upload a PDF and ask questions. Uses **{OLLAMA_MODEL}** running locally via Ollama "
        "with hybrid retrieval (BM25 + n-gram + RRF). Tables are extracted as structured markdown."
    )

    with st.sidebar:
        st.header("⚙️ Settings")
        st.caption(f"🤖 Model: `{OLLAMA_MODEL}`")
        st.caption(f"🖥️ Running: locally via Ollama")
        ollama_ok = check_ollama()
        if ollama_ok:
            st.success(f"✅ Ollama running · {OLLAMA_MODEL} ready")
        else:
            st.error(
                f"❌ Ollama not running or `{OLLAMA_MODEL}` not pulled.\n\n"
                "Install from https://ollama.com/download\n"
                f"Then run: `ollama pull {OLLAMA_MODEL}`"
            )
        st.slider("Retrieved chunks (top K)", 2, 10, key="top_k")
        st.markdown("---")
        if st.button("🗑️ Clear chat and reload PDF"):
            reset_session()

    uploaded_file = st.file_uploader(
        "Upload PDF", type=["pdf"], help="Supports text-based PDFs with tables, text, and mixed content."
    )

    if uploaded_file is not None:
        if not st.session_state.pdf_name:
            with st.spinner("📖 Extracting text and tables from PDF..."):
                try:
                    pdf_text = extract_pdf_text(uploaded_file)
                except Exception as e:
                    st.error(f"Failed to read PDF: {e}")
                    return
                if not pdf_text.strip():
                    st.error("Could not extract any text from this PDF. Please upload a text-based PDF.")
                    return
                chunks = build_chunks(pdf_text)
                table_chunks = [c for c in chunks if c.get("is_table")]
                st.session_state.pdf_name = uploaded_file.name
                st.session_state.chunks = chunks
                st.session_state.total_pages = len(set(chunk["page"] for chunk in chunks))
                st.session_state.total_chunks = len(chunks)
                st.session_state.table_count = len(table_chunks)
                st.session_state.messages = [
                    {
                        "role": "assistant",
                        "content": (
                            f"✅ **\"{uploaded_file.name}\"** processed successfully!\n\n"
                            f"📄 **{st.session_state.total_pages}** pages → "
                            f"**{st.session_state.total_chunks}** chunks indexed "
                            f"(including **{st.session_state.table_count}** table blocks)\n\n"
                            "🔍 Ready to answer questions about text, tables, and all content."
                        ),
                    }
                ]

    if st.session_state.messages:
        for message in st.session_state.messages:
            display_message(message)

    if st.session_state.pdf_name:
        st.markdown(
            f"### 📄 {st.session_state.pdf_name}\n"
            f"**Pages:** {st.session_state.total_pages} · "
            f"**Chunks:** {st.session_state.total_chunks} · "
            f"**Tables:** {st.session_state.table_count}"
        )

        question = st.chat_input("Ask a question about the document...")

        if question:
            # 1. Immediately show user's question
            with st.chat_message("user"):
                st.markdown(question)
            
            # 2. Retrieve & Generate response in real-time
            with st.chat_message("assistant"):
                with st.spinner(f"🔍 Analyzing document using {OLLAMA_MODEL}..."):
                    retrieved = hybrid_retrieve(question, st.session_state.chunks, st.session_state.top_k)
                    context_text = "\n\n---\n\n".join(
                        [
                            f"[Page {chunk['page']}, Chunk {i + 1}{'  📊TABLE' if chunk.get('is_table') else ''}]:\n{chunk['content']}"
                            for i, chunk in enumerate(retrieved)
                        ]
                    )
                    chat_history = "\n".join(
                        [
                            f"User: {msg['content']}" if msg["role"] == "user" else f"Assistant: {msg['content']}"
                            for msg in st.session_state.messages[-6:]
                        ]
                    )
                    prompt = build_prompt(context_text, chat_history, question)
                    try:
                        answer = query_ollama(prompt)
                    except Exception as exc:
                        st.error(str(exc))
                        return
                    
                    st.markdown(answer)
                    if retrieved:
                        with st.expander("Show retrieved source chunks", expanded=False):
                            for src in retrieved:
                                tag = "📊 TABLE" if src.get("is_table") else "📄 Text"
                                st.markdown(
                                    f"- {tag} · Page {src['page']} · Chunk {src['chunk_index'] + 1} · Score {src.get('score', 0):.4f}\n\n"
                                    f"{src['content']}"
                                )

            # Append to history and rerun to persist
            st.session_state.messages.append({"role": "user", "content": question})
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "sources": retrieved,
                }
            )
            st.rerun()

    st.markdown(
        "---\n"
        f"Built with Streamlit · {OLLAMA_MODEL} (Ollama local) · pdfplumber table extraction · Hybrid RAG (BM25 + RRF)"
    )


if __name__ == "__main__":
    main()
