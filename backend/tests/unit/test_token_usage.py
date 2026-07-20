"""Token accounting exists so "where did the spend go" is a SQL query against
agent_audit_log rather than an estimate read off the prompts. These tests pin
the two ways that number goes quietly wrong: dropping the tool-calling loop's
earlier calls, and losing usage entirely to structured output."""

import pytest
from langchain_core.messages import AIMessage

from app.core.llm import ainvoke_structured, token_usage


def _msg(input_tokens: int, output_tokens: int) -> AIMessage:
    return AIMessage(
        content="",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


def test_sums_across_a_tool_calling_loop():
    """The expensive step is several calls over a growing message list. Counting
    only the last one would understate it by most of its value."""
    usage = token_usage(_msg(100, 20), _msg(400, 30), _msg(900, 40))
    assert usage == {"input_tokens": 1400, "output_tokens": 90}


def test_single_message_is_reported_as_is():
    assert token_usage(_msg(50, 10)) == {"input_tokens": 50, "output_tokens": 10}


def test_missing_usage_metadata_counts_as_zero_not_a_crash():
    """Not every provider populates usage_metadata. A missing count must not
    take down the node whose work it was only describing."""
    assert token_usage(AIMessage(content="x"), None) == {"input_tokens": 0, "output_tokens": 0}


class _FakeStructured:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, messages):
        return self._payload


class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    def with_structured_output(self, schema, include_raw=False):
        assert include_raw, "usage is lost unless the raw AIMessage is kept"
        return _FakeStructured(self._payload)


async def test_structured_call_returns_both_the_parsed_object_and_its_usage():
    llm = _FakeLLM({"raw": _msg(700, 120), "parsed": {"ok": True}, "parsing_error": None})
    parsed, usage = await ainvoke_structured(llm, dict, [])
    assert parsed == {"ok": True}
    assert usage == {"input_tokens": 700, "output_tokens": 120}


async def test_parse_failure_raises_rather_than_returning_none():
    """include_raw turns parse errors into a dict key instead of an exception.
    A node that silently returned None here would be worse than one that fails."""
    llm = _FakeLLM({"raw": _msg(10, 0), "parsed": None, "parsing_error": "bad json"})
    with pytest.raises(ValueError, match="bad json"):
        await ainvoke_structured(llm, dict, [])
