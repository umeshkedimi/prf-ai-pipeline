"""ChatOllama defaults to http://localhost:11434, which only resolves inside
the dockerized api/celery-worker containers themselves — not the host
machine actually running Ollama. get_llm() must forward OLLAMA_BASE_URL
(when set) as ChatOllama's base_url, and leave it alone (real localhost)
when unset, e.g. under a bare `uv run`."""

from app.core.config import Settings
from app.core.llm import get_llm


def test_forwards_configured_ollama_base_url(monkeypatch):
    monkeypatch.setattr(
        "app.core.llm.get_settings",
        lambda: Settings(
            llm_provider="ollama",
            llm_model="qwen2.5:14b",
            ollama_base_url="http://host.docker.internal:11434",
        ),
    )
    llm = get_llm()
    assert llm.base_url == "http://host.docker.internal:11434"


def test_leaves_default_base_url_when_unset(monkeypatch):
    monkeypatch.setattr(
        "app.core.llm.get_settings",
        lambda: Settings(llm_provider="ollama", llm_model="qwen2.5:14b", ollama_base_url=None),
    )
    llm = get_llm()
    assert llm.base_url is None  # unset — ChatOllama's own localhost default applies
