FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2 + compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --timeout 300 --retries 5 -r requirements.txt

# Pre-download the fastembed ONNX model at build time (~50MB).
# Avoids a 30-60s cold-start delay on the first request in production.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

# Run as non-root — principle of least privilege
RUN useradd --system --uid 1001 --no-create-home sovereign

COPY . .
RUN chown -R sovereign:sovereign /app
USER sovereign

EXPOSE 8100 9100

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
  CMD curl -f http://localhost:8100/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100", "--log-level", "info"]
