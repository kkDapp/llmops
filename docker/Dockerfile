# Stage 1: dependency builder
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 --retries=5 --prefix=/install -r requirements.txt && \
    PYTHONPATH=/install/lib/python3.11/site-packages \
    python -m spacy download en_core_web_sm --target /install/lib/python3.11/site-packages

# Stage 2: runtime
FROM python:3.11-slim AS runtime
WORKDIR /app
COPY --from=builder /install /usr/local
COPY config/ ./config/
COPY src/ ./src/
COPY static/ ./static/
COPY .env.example ./.env.example

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
