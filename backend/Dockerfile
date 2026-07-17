FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["python", "-m", "app.main"]
