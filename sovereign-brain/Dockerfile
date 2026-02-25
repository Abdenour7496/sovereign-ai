FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2 + compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as non-root — principle of least privilege
RUN useradd --system --uid 1001 --no-create-home sovereign

COPY . .
RUN chown -R sovereign:sovereign /app
USER sovereign

EXPOSE 8100 9100

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100", "--log-level", "info"]
