"""Print Vendor MCP server — real MCP protocol (streamable-HTTP), backed by a
deterministic fixture map standing in for a real print/mail fulfillment
vendor (e.g. Lob, PostGrid). Run standalone:

    uv run python -m app.mcp_servers.print_vendor.server
"""

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from app.mcp_servers.print_vendor import fixtures

mcp = FastMCP("print_vendor", host="0.0.0.0", port=8103, stateless_http=True)


class PrintOrderConfirmation(BaseModel):
    vendor_order_id: str
    tracking_number: str
    postage_class: str
    turnaround_days: int
    cost: float


@mcp.tool()
async def submit_print_order(reference: str, page_count: int = 1) -> PrintOrderConfirmation:
    """Submits a print-ready mail piece to the vendor and returns its order
    confirmation (tracking number, postage class, turnaround, cost)."""
    return PrintOrderConfirmation(**fixtures.submit_print_order(reference, page_count))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
