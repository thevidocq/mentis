# Two images from one Dockerfile:
#   api    - FastAPI (target "api")
#   worker - ingestion worker with OCR (target "worker")

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 mentis
COPY pyproject.toml ./
COPY app ./app

FROM base AS api
RUN pip install --no-cache-dir .
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh
USER mentis
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
ENTRYPOINT ["./docker-entrypoint.sh"]

FROM base AS worker
# Tesseract OCR with English and Italian language data.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-ita \
 && rm -rf /var/lib/apt/lists/*
# Set PARSER_EXTRAS=worker,docling at build time to include the optional Docling parser.
ARG PARSER_EXTRAS=worker
RUN pip install --no-cache-dir ".[${PARSER_EXTRAS}]"
USER mentis
CMD ["python", "-m", "app.worker"]
