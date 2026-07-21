from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

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


def token_usage(*messages: BaseMessage | None) -> dict[str, int]:
    """Total tokens across one or more responses.

    Takes several messages because a tool-calling loop makes several LLM calls
    for one logical step — the cost of that step is their sum, and reporting
    only the last call would understate it by most of its value.
    """
    totals = {"input_tokens": 0, "output_tokens": 0}
    for message in messages:
        usage = getattr(message, "usage_metadata", None) or {}
        totals["input_tokens"] += usage.get("input_tokens") or 0
        totals["output_tokens"] += usage.get("output_tokens") or 0
    return totals


# Local Ollama models occasionally fail to emit valid structured output (e.g. a
# confidence value outside the schema's 0.0-1.0 range) as a transient hiccup,
# not a repeatable capability gap — see CLAUDE.local.md item 3 for the sweep
# evidence. Bounded so a genuinely broken input still fails loudly.
STRUCTURED_OUTPUT_MAX_ATTEMPTS = 3


async def ainvoke_structured(llm: BaseChatModel, schema: Any, messages: list) -> tuple[Any, dict]:
    """Structured-output call that also returns its token usage.

    `with_structured_output` normally hands back only the parsed object and
    drops the AIMessage carrying usage_metadata, which is exactly the data
    needed to attribute spend to a node. `include_raw=True` keeps both.

    include_raw also suppresses parse failures into a `parsing_error` key
    instead of raising, so re-raise to preserve the original behaviour — a
    node that silently returns None here would be worse than one that fails.
    Retried a small bounded number of times before that re-raise.
    """
    last_error: ValueError | None = None
    for _ in range(STRUCTURED_OUTPUT_MAX_ATTEMPTS):
        result = await llm.with_structured_output(schema, include_raw=True).ainvoke(messages)
        if not result.get("parsing_error"):
            return result["parsed"], token_usage(result.get("raw"))
        last_error = ValueError(f"structured output failed to parse: {result['parsing_error']}")
    raise last_error


def get_judge_llm(**kwargs) -> BaseChatModel:
    """The model used for LLM-as-judge evaluation scoring. Separate from the
    pipeline's own model on purpose (see get_llm) and cheaper, since judging is
    a narrower task run over many cases."""
    settings = get_settings()
    return get_llm(model=settings.judge_model, provider=settings.judge_provider, **kwargs)
