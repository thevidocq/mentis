# Two images from one Dockerfile:
#   api    - FastAPI (target "api")
#   worker - ingestion worker with OCR (target "worker")
#
# Layer order keeps slow steps cached across releases: system packages first, then Python
# dependencies installed from a list extracted from pyproject.toml (the list does not contain
# the version, so a version bump or a code change does not reinstall them), then the app code.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 mentis

# Dependency lists, one file per group: base.txt and <extra>.txt for each optional extra.
# This stage reruns when pyproject.toml changes, but its output is byte-identical unless a
# dependency changed, so the COPY --from below (checked by content) stays cached.
FROM base AS requirements
COPY pyproject.toml ./
RUN python -c "import pathlib, tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; d = pathlib.Path('/requirements'); d.mkdir(); (d / 'base.txt').write_text('\n'.join(p['dependencies']) + '\n'); [(d / f'{k}.txt').write_text('\n'.join(v) + '\n') for k, v in p.get('optional-dependencies', {}).items()]"

FROM base AS api
COPY --from=requirements /requirements /requirements
RUN pip install --no-cache-dir -r /requirements/base.txt
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --no-deps .
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
COPY --from=requirements /requirements /requirements
RUN set -e; reqs="-r /requirements/base.txt"; \
    for extra in $(echo "$PARSER_EXTRAS" | tr ',' ' '); do \
      [ -f "/requirements/$extra.txt" ] || { echo "Unknown extra in PARSER_EXTRAS: $extra" >&2; exit 1; }; \
      reqs="$reqs -r /requirements/$extra.txt"; \
    done; \
    pip install --no-cache-dir $reqs
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --no-deps .
USER mentis
CMD ["python", "-m", "app.worker"]
