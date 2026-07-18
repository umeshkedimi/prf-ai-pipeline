import json
from typing import Any


def parse_single(result: Any) -> dict:
    """langchain-mcp-adapters returns a tool result as either a raw JSON string or
    a list of `{'type': 'text', 'text': <json>}` content blocks, depending on the
    MCP server's encoding. Use for tools that return one object."""
    if isinstance(result, str):
        return json.loads(result)
    if isinstance(result, list) and result:
        return json.loads(result[0]["text"])
    return {}


def parse_list(result: Any) -> list[dict]:
    """Use for tools that return a list — FastMCP encodes each list element as
    its own content block rather than a single JSON array block."""
    if isinstance(result, str):
        parsed = json.loads(result)
        return parsed if isinstance(parsed, list) else [parsed]
    if isinstance(result, list):
        return [
            json.loads(block["text"])
            for block in result
            if isinstance(block, dict) and block.get("type") == "text"
        ]
    return []
