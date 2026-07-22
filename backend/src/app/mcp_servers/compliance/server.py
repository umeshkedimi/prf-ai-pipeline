"""Compliance MCP server — real MCP protocol (streamable-HTTP), backed by a
deterministic fixture map standing in for a real charitable-solicitation
compliance/registration system. Run standalone:

    uv run python -m app.mcp_servers.compliance.server
"""

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from app.mcp_servers.compliance import fixtures

mcp = FastMCP("compliance", host="0.0.0.0", port=8102, stateless_http=True)


class DisclosureRequirements(BaseModel):
    registered_to_solicit: bool
    required_disclosures: list[str]


@mcp.tool()
async def get_disclosure_requirements(state: str = "") -> DisclosureRequirements:
    """Whether the org is registered to solicit donations in a US state, and
    the legally required disclosure text for mailings sent there."""
    return DisclosureRequirements(**fixtures.get_disclosure_requirements(state))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
