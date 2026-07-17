"""CRM MCP server — real MCP protocol (streamable-HTTP), backed by our own Postgres
tables standing in for a real CRM's API. Run standalone:

    uv run python -m app.mcp_servers.crm.server
"""

from mcp.server.fastmcp import FastMCP

from app.db.session import db_session
from app.mcp_servers.crm import queries
from app.mcp_servers.crm.queries import DonationRecord, DonorProfile, DuplicateCandidate

mcp = FastMCP("crm", host="0.0.0.0", port=8100, stateless_http=True)


@mcp.tool()
async def get_donor_profile(donor_id: str) -> DonorProfile | dict:
    """Look up a donor's CRM profile, including do-not-contact and suppression status."""
    async with db_session() as session:
        profile = await queries.get_donor_profile(session, donor_id)
    if profile is None:
        return {"error": f"donor {donor_id} not found"}
    return profile


@mcp.tool()
async def get_donation_history(donor_id: str) -> list[DonationRecord]:
    """Return a donor's full donation history, most recent first."""
    async with db_session() as session:
        return await queries.get_donation_history(session, donor_id)


@mcp.tool()
async def find_potential_duplicate_donors(
    name: str, address: str, exclude_donor_id: str
) -> list[DuplicateCandidate]:
    """Fuzzy-match candidate duplicate donor records by name/address similarity (pg_trgm)."""
    async with db_session() as session:
        return await queries.find_potential_duplicate_donors(session, name, address, exclude_donor_id)


@mcp.tool()
async def update_campaign_status(campaign_id: str, donor_id: str, status: str) -> dict:
    """Update a campaign's status (e.g. after a donor's letter has been generated/mailed)."""
    async with db_session() as session:
        return await queries.update_campaign_status(session, campaign_id, donor_id, status)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
