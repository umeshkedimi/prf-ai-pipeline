FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
# The RAG corpus scripts/ingest_knowledge.py reads. Previously omitted, which
# made the image ship a script without its data -- invisible under
# docker-compose, where ingest was always run from the host via `uv run`, and an
# immediate FileNotFoundError the first time a Kubernetes Job tried to provision
# a fresh database. 24K.
COPY knowledge ./knowledge

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
