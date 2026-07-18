"""Address MCP server — real MCP protocol (streamable-HTTP), backed by a
deterministic fixture map standing in for a real address-verification vendor
(e.g. USPS CASS/NCOA). Run standalone:

    uv run python -m app.mcp_servers.address.server
"""

from mcp.server.fastmcp import FastMCP

from app.mcp_servers.address import fixtures
from app.mcp_servers.address.fixtures import AddressVerification, ForwardingLookup

mcp = FastMCP("address", host="0.0.0.0", port=8101, stateless_http=True)


@mcp.tool()
async def verify_address(
    address_line1: str, city: str = "", state: str = "", postal_code: str = ""
) -> AddressVerification:
    """Validate and standardize a mailing address; flags moved/vacant/PO-box addresses."""
    return AddressVerification(**fixtures.verify_address(address_line1, city, state, postal_code))


@mcp.tool()
async def lookup_new_address(
    address_line1: str, city: str = "", state: str = "", postal_code: str = ""
) -> ForwardingLookup:
    """Look up a forwarding/new address for a donor known to have moved."""
    return ForwardingLookup(**fixtures.lookup_new_address(address_line1, city, state, postal_code))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
