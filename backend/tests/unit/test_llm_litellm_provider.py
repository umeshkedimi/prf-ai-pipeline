"""LLM_PROVIDER=litellm routes through the local proxy rather than to a vendor.

The proxy is OpenAI-compatible, so the client is a plain OpenAI client pointed
at a different host — get_llm() has to translate the provider name while
keeping the runaway-generation cap the direct-Ollama path already enforces.
"""

from langchain_ollama import ChatOllama

from app.core.config import Settings
from app.core.llm import get_llm


def _settings(**overrides) -> Settings:
    base = {"llm_provider": "litellm", "llm_model": "pipeline"}
    return Settings(**{**base, **overrides})


def test_points_the_client_at_the_proxy(monkeypatch):
    monkeypatch.setattr(
        "app.core.llm.get_settings",
        lambda: _settings(
            litellm_base_url="http://litellm:4000/v1", litellm_api_key="sk-test"
        ),
    )
    llm = get_llm()
    assert llm.openai_api_base == "http://litellm:4000/v1"
    assert llm.openai_api_key.get_secret_value() == "sk-test"
    # The alias from litellm/config.yaml, passed through untranslated -- the
    # proxy, not this process, decides which vendor model it resolves to.
    assert llm.model_name == "pipeline"


def test_caps_generation_length_like_the_direct_ollama_path(monkeypatch):
    """A local generation that never emits a stop token hung a real eval sweep
    past 32,000 tokens. Routing through a proxy must not drop that guard just
    because the parameter is spelled max_tokens on this side."""
    monkeypatch.setattr("app.core.llm.get_settings", lambda: _settings())
    assert get_llm().max_tokens == 2048


def test_explicit_kwargs_win_over_the_defaults(monkeypatch):
    monkeypatch.setattr("app.core.llm.get_settings", lambda: _settings())
    llm = get_llm(max_tokens=64, base_url="http://elsewhere:4000/v1")
    assert llm.max_tokens == 64
    assert llm.openai_api_base == "http://elsewhere:4000/v1"


def test_judge_routes_through_the_proxy_on_its_own_alias(monkeypatch):
    """The judge must stay a different model than the pipeline (a model grading
    its own output is biased toward it). Through the proxy that separation is
    two aliases, so the judge's provider/model must not collapse into the
    pipeline's."""
    from app.core.llm import get_judge_llm

    monkeypatch.setattr(
        "app.core.llm.get_settings",
        lambda: _settings(judge_provider="litellm", judge_model="judge"),
    )
    assert get_judge_llm().model_name == "judge"


def test_blank_env_values_fall_back_to_defaults():
    """`LITELLM_BASE_URL=` in a copied .env is "unset", not "". Binding the
    empty string would send calls to the real OpenAI API carrying the proxy's
    key -- a confusing failure the non-None default exists to prevent."""
    settings = _settings(litellm_base_url="", litellm_api_key="")
    assert settings.litellm_base_url == "http://localhost:4000/v1"
    assert settings.litellm_api_key == "sk-prf-local"


def test_other_providers_are_untouched(monkeypatch):
    """The litellm branch must not become the path everything takes -- switching
    back to a direct provider is meant to stay a one-line .env change."""
    monkeypatch.setattr(
        "app.core.llm.get_settings",
        lambda: Settings(
            llm_provider="ollama", llm_model="qwen2.5:14b", ollama_base_url=None
        ),
    )
    llm = get_llm()
    assert isinstance(llm, ChatOllama)
    assert llm.num_predict == 2048
