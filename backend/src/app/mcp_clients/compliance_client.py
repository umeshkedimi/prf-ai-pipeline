from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import get_settings
from app.mcp_clients.parsing import parse_list, parse_single

__all__ = ["get_compliance_tools", "parse_list", "parse_single"]


async def get_compliance_tools() -> dict[str, BaseTool]:
    settings = get_settings()
    client = MultiServerMCPClient(
        {"compliance": {"url": settings.mcp_compliance_url, "transport": "streamable_http"}}
    )
    tools = await client.get_tools()
    return {tool.name: tool for tool in tools}
