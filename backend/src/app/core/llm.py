from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings


def get_llm(
    model: str | None = None,
    provider: str | None = None,
    **kwargs,
) -> BaseChatModel:
    """Provider-agnostic chat model, defaulting to Anthropic per LLM_PROVIDER/LLM_MODEL.

    Deliberately does not hardcode sampling parameters (temperature/top_p/top_k) —
    Claude Sonnet 5 rejects non-default values for several of these, and other
    providers have different valid ranges/defaults. Only what's explicitly passed
    via kwargs is forwarded, keeping this safe to point at other providers later.

    `model`/`provider` override the configured defaults. The evaluation framework
    uses this to run its LLM-as-judge scorer on a *different* model than the one
    being judged — a model grading its own output is measurably biased toward it.
    """
    settings = get_settings()
    resolved_provider = provider or settings.llm_provider
    model_kwargs = dict(kwargs)
    if resolved_provider == "anthropic" and settings.anthropic_api_key:
        model_kwargs.setdefault("api_key", settings.anthropic_api_key)
    elif resolved_provider == "google_genai" and settings.google_api_key:
        # langchain-google-genai names this kwarg google_api_key, not api_key.
        model_kwargs.setdefault("google_api_key", settings.google_api_key)
    return init_chat_model(
        model=model or settings.llm_model,
        model_provider=resolved_provider,
        **model_kwargs,
    )


def get_judge_llm(**kwargs) -> BaseChatModel:
    """The model used for LLM-as-judge evaluation scoring. Separate from the
    pipeline's own model on purpose (see get_llm) and cheaper, since judging is
    a narrower task run over many cases."""
    settings = get_settings()
    return get_llm(model=settings.judge_model, provider=settings.judge_provider, **kwargs)
