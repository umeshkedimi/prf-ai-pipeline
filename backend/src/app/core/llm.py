from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings


def get_llm(**kwargs) -> BaseChatModel:
    """Provider-agnostic chat model, defaulting to Anthropic per LLM_PROVIDER/LLM_MODEL.

    Deliberately does not hardcode sampling parameters (temperature/top_p/top_k) —
    Claude Sonnet 5 rejects non-default values for several of these, and other
    providers have different valid ranges/defaults. Only what's explicitly passed
    via kwargs is forwarded, keeping this safe to point at other providers later.
    """
    settings = get_settings()
    model_kwargs = dict(kwargs)
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        model_kwargs.setdefault("api_key", settings.anthropic_api_key)
    return init_chat_model(
        model=settings.llm_model,
        model_provider=settings.llm_provider,
        **model_kwargs,
    )
