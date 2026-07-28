import os
from dotenv import load_dotenv

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_huggingface import (
    HuggingFaceEmbeddings,
    HuggingFaceEndpoint,
    ChatHuggingFace,
)

from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough


# ==============================
# Load Environment Variables
# ==============================

load_dotenv()

HF_TOKEN = os.getenv("HUGGINGFACEHUB_API_TOKEN")

if not HF_TOKEN:
    raise RuntimeError("Please set HUGGINGFACEHUB_API_TOKEN in your .env file before running the app.")


# ==============================
# Load PDF
# ==============================

loader = PyPDFLoader("DocMate_FYP_MidReport (1).pdf")
documents = loader.load()

print(f"Loaded {len(documents)} pages.")


# ==============================
# Split Documents
# ==============================

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200
)

chunks = splitter.split_documents(documents)

print(f"Created {len(chunks)} chunks.")


# ==============================
# Embedding Model
# ==============================

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


# ==============================
# FAISS Vector Store
# ==============================

vector_store = FAISS.from_documents(
    chunks,
    embeddings
)


# ==============================
# Dense Retriever (FAISS)
# ==============================

faiss_retriever = vector_store.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 3}
)


# ==============================
# Sparse Retriever (BM25)
# ==============================

bm25_retriever = BM25Retriever.from_documents(chunks)
bm25_retriever.k = 3


# ==============================
# Hybrid Retriever
# ==============================


def hybrid_retrieve(question, k=3):
    faiss_results = faiss_retriever.invoke(question)
    bm25_results = bm25_retriever.invoke(question)

    combined = []
    seen = set()

    for doc in faiss_results + bm25_results:
        key = (doc.page_content, doc.metadata.get("source"))
        if key not in seen:
            combined.append(doc)
            seen.add(key)

    return combined[:k]


# ==============================
# HuggingFace Endpoint
# ==============================

llm = HuggingFaceEndpoint(
    repo_id="meta-llama/Llama-3.1-8B-Instruct",
    huggingfacehub_api_token=HF_TOKEN,
    temperature=0.3,
    max_new_tokens=512,
)

chat = ChatHuggingFace(llm=llm)


# ==============================
# Prompt
# ==============================

prompt = PromptTemplate(
    template="""
You are an AI assistant.

Answer ONLY using the provided context.
If the answer is not present in the context, reply:
"I couldn't find the answer in the provided document."

Context:
{context}

Question:
{question}

Answer:
""",
    input_variables=["context", "question"],
)


# ==============================
# Output Parser
# ==============================

parser = StrOutputParser()


# ==============================
# Helper Function
# ==============================

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


def retrieve_context(question):
    docs = hybrid_retrieve(question)
    return format_docs(docs)


# ==============================
# Debug Retrieved Context
# ==============================

question = "What is DocMate?"

retrieved_docs = hybrid_retrieve(question)

print("\n" + "=" * 80)
print("Retrieved Context")
print("=" * 80)

for i, doc in enumerate(retrieved_docs, start=1):
    print(f"\nChunk {i}")
    print("-" * 80)
    print(doc.page_content[:500])

print("\n" + "=" * 80)


# ==============================
# RAG Chain
# ==============================

chain = (
    {
        "context": RunnablePassthrough() | retrieve_context,
        "question": RunnablePassthrough(),
    }
    | prompt
    | chat
    | parser
)


# ==============================
# Ask Question
# ==============================

response = chain.invoke(question)

print("\n" + "=" * 80)
print("Final Answer")
print("=" * 80)
print(response)