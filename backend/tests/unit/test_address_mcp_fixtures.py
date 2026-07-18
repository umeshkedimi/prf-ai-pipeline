"""Pure unit tests for the Address MCP server's fixture logic — no DB, no
network, no LLM (unlike the CRM MCP tests, which need real Postgres)."""

from app.mcp_servers.address import fixtures


def test_verify_address_missing_address_line1():
    result = fixtures.verify_address("", "Anywhere", "TX", "00000")
    assert result["valid"] is False
    assert result["deliverable"] is False


def test_verify_address_moved_fixture():
    result = fixtures.verify_address("410 Willow St", "Denver", "CO", "80203")
    assert result["moved"] is True
    assert result["deliverable"] is False
    assert result["vacant"] is False


def test_verify_address_vacant_fixture():
    result = fixtures.verify_address("999 Ghost Ave", "Detroit", "MI", "48201")
    assert result["vacant"] is True
    assert result["valid"] is False
    assert result["deliverable"] is False


def test_verify_address_po_box_fixture():
    result = fixtures.verify_address("PO Box 9911", "Reno", "NV", "89501")
    assert result["po_box"] is True
    assert result["deliverable"] is True


def test_verify_address_fallback_valid_default():
    result = fixtures.verify_address("1 Unfixtured Way", "Nowhere", "TX", "00000")
    assert result["valid"] is True
    assert result["deliverable"] is True
    assert result["moved"] is False
    assert result["po_box"] is False


def test_verify_address_fallback_detects_po_box_by_text():
    result = fixtures.verify_address("P.O. Box 42", "Nowhere", "TX", "00000")
    assert result["po_box"] is True


def test_lookup_new_address_found():
    result = fixtures.lookup_new_address("410 Willow St", "Denver", "CO", "80203")
    assert result["found"] is True
    assert result["new_address"] == "1225 Pine St, Denver, CO 80218"
    assert 0 < result["confidence"] < 1


def test_lookup_new_address_not_found():
    result = fixtures.lookup_new_address("999 Ghost Ave", "Detroit", "MI", "48201")
    assert result["found"] is False
    assert result["new_address"] is None


def test_lookup_new_address_unfixtured_defaults_not_found():
    result = fixtures.lookup_new_address("1 Unfixtured Way", "Nowhere", "TX", "00000")
    assert result["found"] is False
