"""Pure unit tests for the Print Vendor MCP server's fixture logic — no DB,
no network, no LLM."""

from app.mcp_servers.print_vendor import fixtures


def test_submit_print_order_first_class_for_short_letters():
    result = fixtures.submit_print_order("PRF-AAAAAAAA", page_count=1)
    assert result["postage_class"] == "first_class"
    assert result["turnaround_days"] == 3


def test_submit_print_order_standard_for_long_letters():
    result = fixtures.submit_print_order("PRF-AAAAAAAA", page_count=3)
    assert result["postage_class"] == "standard"
    assert result["turnaround_days"] == 7


def test_submit_print_order_deterministic_for_same_reference():
    first = fixtures.submit_print_order("PRF-BBBBBBBB", page_count=1)
    second = fixtures.submit_print_order("PRF-BBBBBBBB", page_count=1)
    assert first == second


def test_submit_print_order_distinct_references_get_distinct_ids():
    first = fixtures.submit_print_order("PRF-CCCCCCCC", page_count=1)
    second = fixtures.submit_print_order("PRF-DDDDDDDD", page_count=1)
    assert first["vendor_order_id"] != second["vendor_order_id"]
    assert first["tracking_number"] != second["tracking_number"]


def test_submit_print_order_tracking_number_is_numeric():
    result = fixtures.submit_print_order("PRF-EEEEEEEE", page_count=1)
    assert result["tracking_number"].isdigit()
