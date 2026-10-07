# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Models live outside the /app/data volume so the mount never hides the baked-in copies.
    HF_HOME=/opt/hf-cache \
    DATA_DIR=/app/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-urd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# CPU-only torch keeps the image far smaller than the default CUDA build.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

# Non-root user. Ownership is set while copying (COPY --chown) and by running the model step as
# this user: a later `chown -R` would store every model file a second time in a new layer (+1 GB).
RUN useradd --create-home --uid 10001 askmypdf \
    && mkdir -p /app/data /opt/hf-cache/hub \
    && chown askmypdf:askmypdf /app/data /opt/hf-cache /opt/hf-cache/hub
USER askmypdf

# Bake the embedding + reranker models into the image (own layer: code changes don't re-download).
# Override with --build-arg, or set PRELOAD_MODELS=false for a smaller image that downloads at first start.
# Optional: models already downloaded on the build machine can be placed in backend/hf-cache/
# (same layout as ~/.cache/huggingface/hub) to skip downloading them again; the folder may be empty.
COPY --chown=askmypdf:askmypdf hf-cache/ /opt/hf-cache/hub/
ARG PRELOAD_MODELS=true
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ARG RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RUN if [ "$PRELOAD_MODELS" = "true" ]; then python -c "\
from huggingface_hub import snapshot_download; \
pats = ['*.json', '*.txt', 'model.safetensors', 'sentencepiece.bpe.model', 'tokenizer*', '1_Pooling/*']; \
[snapshot_download(m, allow_patterns=pats) for m in ['$EMBEDDING_MODEL', '$RERANKER_MODEL'] if m]"; fi

COPY app ./app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
