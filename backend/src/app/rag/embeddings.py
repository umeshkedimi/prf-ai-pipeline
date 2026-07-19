from functools import lru_cache

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings

from app.core.config import get_settings


@lru_cache
def get_embeddings() -> Embeddings:
    """Provider-agnostic embedding model, defaulting to OpenAI per
    EMBEDDING_PROVIDER/EMBEDDING_MODEL — Anthropic has no embeddings API.

    Mirrors core/llm.py:get_llm(): only forwards an explicit api_key when we
    have one in settings, so it stays safe to point at another provider later.
    Cached because the underlying client is reusable and cheap to share.
    """
    settings = get_settings()
    kwargs = {}
    if settings.embedding_provider == "openai" and settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    return init_embeddings(
        f"{settings.embedding_provider}:{settings.embedding_model}",
        **kwargs,
    )
