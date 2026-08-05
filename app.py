import os
import re
import uuid
from typing import Dict, List, Optional

import requests
import streamlit as st
from langchain.text_splitter import CharacterTextSplitter
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv()

HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACEHUB_API_TOKEN")
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"

st.set_page_config(page_title="AskMyPDF", page_icon="⚡", layout="wide")

PROMPT_TEMPLATE = """You are AskMyPDF, a precise document question-answering assistant.

STRICT RULES (follow ALL of these exactly):
1. Answer ONLY using facts explicitly stated in the DOCUMENT CONTEXT below.
2. If the answer is not in the context, say exactly: "This information is not available in the provided document."
3. DO NOT invent, guess, or extrapolate any facts, dates, numbers, names, or values.
4. When citing numbers, marks, dates, semesters — copy them EXACTLY as written in the context.
5. Keep answers concise and factual. Use bullet points for lists.
6. Respond in the SAME language as the question (if Urdu/Roman-Urdu → reply in Roman Urdu).
7. If asked about tables, read row and column headers carefully before answering.

DOCUMENT CONTEXT:
---
{context}
---

CHAT HISTORY (for follow-up context):
{chat_history}

User: {question}
Assistant:"""

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


def bm25_score(query_tokens: List[str], doc_tokens: List[str], avg_doc_length: float, k1: float = 1.5, b: float = 0.75) -> float:
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
    q_ngrams = {q[i : i + n] for i in range(max(len(q) - n + 1, 0))}
    d_ngrams = {d[i : i + n] for i in range(max(len(d) - n + 1, 0))}
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
        bm25_ranked.append({
            **chunk,
            "score": bm25_score(query_tokens, doc_tokens, avg_len),
        })
        ngram_ranked.append({
            **chunk,
            "score": ngram_similarity(query, chunk["content"]),
        })

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


def extract_pdf_text(uploaded_file) -> str:
    reader = PdfReader(uploaded_file)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\f\n".join(pages)


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+|\n\n+", text)
    chunks: List[str] = []
    current = ""
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
                }
            )
            chunk_idx += 1
    return chunks


def query_huggingface(prompt: str) -> str:
    if not HUGGINGFACE_TOKEN:
        raise RuntimeError(
            "HuggingFace API token is not configured. Set HUGGINGFACEHUB_API_TOKEN in your environment."
        )
    response = requests.post(
        f"https://api-inference.huggingface.co/models/{MODEL_ID}",
        headers={
            "Authorization": f"Bearer {HUGGINGFACE_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 800,
                "temperature": 0.1,
                "top_p": 0.9,
                "repetition_penalty": 1.1,
                "do_sample": True,
                "return_full_text": False,
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data["error"])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get("generated_text", "").strip()
    raise RuntimeError("Unexpected response from HuggingFace inference API.")


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


def reset_session() -> None:
    st.session_state.messages = []
    st.session_state.chunks = []
    st.session_state.pdf_name = ""
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.total_pages = 0
    st.session_state.total_chunks = 0


def display_message(message: Dict) -> None:
    role = message.get("role")
    content = message.get("content", "")
    sources = message.get("sources")
    if role == "user":
        st.markdown(f"**🧑 User:** {content}")
    else:
        st.markdown(f"**🤖 Assistant:** {content}")
        if sources:
            with st.expander("Show retrieved source chunks", expanded=False):
                for src in sources:
                    st.markdown(
                        f"- Page {src['page']} · Chunk {src['chunk_index'] + 1} · Score {src['score']:.4f}\n  > {src['content']}"
                    )


def main() -> None:
    initialize_state()

    st.title("⚡ AskMyPDF — Streamlit RAG Chatbot")
    st.write(
        "Upload a PDF and ask questions. The app uses hybrid retrieval (BM25 + n-gram + RRF) and HuggingFace inference for precise document answers."
    )

    with st.sidebar:
        st.header("Settings")
        if HUGGINGFACE_TOKEN:
            st.success("HuggingFace API token loaded")
        else:
            st.error(
                "Set HUGGINGFACEHUB_API_TOKEN in your environment or .env file to enable model inference."
            )
        st.slider("Retrieved chunks (top K)", 2, 10, key="top_k")
        st.markdown("---")
        if st.button("Clear chat and reload PDF"):
            reset_session()

    uploaded_file = st.file_uploader("Upload PDF", type=["pdf"], help="Text-based PDFs only.")

    if uploaded_file is not None:
        if not st.session_state.pdf_name:
            with st.spinner("Extracting text and building document chunks..."):
                pdf_text = extract_pdf_text(uploaded_file)
                if not pdf_text.strip():
                    st.error("Could not extract any text from this PDF. Please upload a text-based PDF.")
                    return
                chunks = build_chunks(pdf_text)
                st.session_state.pdf_name = uploaded_file.name
                st.session_state.chunks = chunks
                st.session_state.total_pages = len(set(chunk["page"] for chunk in chunks))
                st.session_state.total_chunks = len(chunks)
                st.session_state.messages = [
                    {
                        "role": "assistant",
                        "content": (
                            f"✅ \"{uploaded_file.name}\" has been processed successfully!\n\n"
                            f"📄 {st.session_state.total_pages} pages → {st.session_state.total_chunks} optimized chunks indexed.\n\n"
                            "🔍 Ready to answer your questions with Hybrid RAG (BM25 + RRF)."
                        ),
                    }
                ]

    if st.session_state.pdf_name:
        st.markdown(
            f"### Document: {st.session_state.pdf_name} \n\n"
            f"**Pages:** {st.session_state.total_pages} · **Chunks:** {st.session_state.total_chunks}"
        )

        question = st.text_input(
            "Ask a question about the document",
            key="question_input",
            placeholder="Type your question and press Enter...",
        )

        if question:
            with st.spinner("Retrieving relevant chunks and generating answer..."):
                retrieved = hybrid_retrieve(question, st.session_state.chunks, st.session_state.top_k)
                context_text = "\n\n---\n\n".join(
                    [f"[Page {chunk['page']}, Chunk {i + 1}]:\n{chunk['content']}" for i, chunk in enumerate(retrieved)]
                )
                chat_history = "\n".join(
                    [
                        f"User: {msg['content']}" if msg["role"] == "user" else f"Assistant: {msg['content']}"
                        for msg in st.session_state.messages[-8:]
                    ]
                )
                prompt = build_prompt(context_text, chat_history, question)
                try:
                    answer = query_huggingface(prompt)
                except Exception as exc:
                    st.error(str(exc))
                    return

                st.session_state.messages.append({"role": "user", "content": question})
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "sources": retrieved,
                    }
                )

                st.experimental_rerun()

    if st.session_state.messages:
        for message in st.session_state.messages:
            display_message(message)

    st.markdown(
        "---\n"
        "Built with Streamlit, LangChain-style chunking, hybrid retrieval, and HuggingFace model inference."
    )


if __name__ == "__main__":
    main()
