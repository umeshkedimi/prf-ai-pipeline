from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Single .env lives at the repo root (alongside docker-compose.yml), not under
# backend/ — resolve it relative to this file so it's found regardless of CWD
# (uv run from backend/, pytest, scripts/, etc). Safe if missing (e.g. in Docker,
# where real env vars are injected directly by docker-compose).
_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    postgres_user: str = "prf"
    postgres_password: str = "prf"
    postgres_db: str = "prf_ai_pipeline"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    database_url: str = "postgresql+asyncpg://prf:prf@localhost:5432/prf_ai_pipeline"
    database_url_sync: str = "postgresql+psycopg://prf:prf@localhost:5432/prf_ai_pipeline"
    checkpointer_database_url: str = "postgresql://prf:prf@localhost:5432/prf_ai_pipeline"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    anthropic_api_key: str | None = None

    mcp_crm_url: str = "http://localhost:8100/mcp"
    mcp_address_url: str = "http://localhost:8101/mcp"

    log_level: str = "INFO"
    confidence_threshold_donor_verification: float = 0.80
    confidence_threshold_address_intelligence: float = 0.80


@lru_cache
def get_settings() -> Settings:
    return Settings()
