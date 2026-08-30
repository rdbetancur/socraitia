# Cloud Run image. Python 3.12-slim on purpose — local dev is 3.14, but
# cryptography and a few transitive deps still compile from source on cp314
# manylinux. 3.12 has wheels. Do not "fix" this back to 3.14.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

FROM base AS builder
COPY requirements.txt .
# No build-essential. If pip tries to compile, the build should fail in the
# open — a silent multi-minute compile on Cloud Build is how deploys slip.
RUN pip install --prefix=/install -r requirements.txt

FROM base AS runtime
COPY --from=builder /install /usr/local
COPY app ./app

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75
