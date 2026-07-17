"""Confirms LLM_PROVIDER/LLM_MODEL are reachable with the configured credentials.

Usage: uv run python scripts/smoke_test_llm.py
"""

from app.core.config import get_settings
from app.core.llm import get_llm


def main() -> None:
    settings = get_settings()
    llm = get_llm()
    response = llm.invoke("Reply with exactly the word: ok")
    print(f"provider={settings.llm_provider} model={settings.llm_model}")
    print(f"response={response.content!r}")


if __name__ == "__main__":
    main()
