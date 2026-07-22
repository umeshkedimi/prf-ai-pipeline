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

    llm_provider: str = "google_genai"
    llm_model: str = "gemini-2.5-flash"
    anthropic_api_key: str | None = None
    google_api_key: str | None = None

    # LLM-as-judge model for the evaluation framework. Deliberately a different
    # (and cheaper) model than the one under evaluation: a model grading its own
    # output is measurably biased toward it.
    judge_provider: str = "google_genai"
    judge_model: str = "gemini-2.5-flash-lite"

    # Embeddings for the campaign-knowledge RAG store. Anthropic has no
    # embeddings API, so this defaults to a hosted OpenAI model; resolved
    # provider-agnostically via LangChain init_embeddings (see rag/embeddings.py).
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    openai_api_key: str | None = None

    mcp_crm_url: str = "http://localhost:8100/mcp"
    mcp_address_url: str = "http://localhost:8101/mcp"
    mcp_compliance_url: str = "http://localhost:8102/mcp"

    log_level: str = "INFO"
    confidence_threshold_donor_verification: float = 0.80
    confidence_threshold_address_intelligence: float = 0.80
    # Advisory (non-blocking) bar, deliberately lower than the factual agents'
    # 0.80: a recommendation's confidence is a prediction about a *future* gift,
    # not an assessment of an existing fact, so it runs honestly lower. ~0.9+ is
    # a rich consistent history; ~0.5-0.7 is a thin but usable one (a single
    # prior gift — entirely normal); below 0.5 means the model has essentially
    # no anchor (no history, or the anchor gift was excluded as anomalous),
    # which is what actually warrants a human glance.
    confidence_threshold_donation_recommendation: float = 0.50
    # Advisory (non-blocking) bar for the letter draft, same reasoning as the
    # recommendation threshold above: drafting is judgment, not a factual
    # assessment. Set slightly higher than recommendation's 0.50 because the
    # draft is graded on groundedness in retrieved knowledge, which is a more
    # concrete thing to be confident or unconfident about than a future gift.
    confidence_threshold_campaign_personalization: float = 0.60
    # Advisory (non-blocking) bar for the letter-content risk review. The
    # *blocking* compliance trigger is deterministic (state solicitation
    # registration, see route_after_disclosures) — this threshold only flags
    # `needs_review` when the LLM's own risk assessment is a close call,
    # same non-blocking role as the recommendation/personalization thresholds.
    confidence_threshold_compliance: float = 0.75
    # A recommended ask at or above this dollar amount is a major-gift decision
    # that pauses for human approval, per the spec's human-review trigger list.
    major_gift_ask_threshold: float = 1000.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
