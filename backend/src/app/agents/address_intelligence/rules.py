"""Address assessment as a decision table.

This used to be an LLM call whose prompt was, line for line, this table: invalid or
vacant -> low confidence; moved with a forwarding address -> weigh the forwarding
confidence; clean -> high confidence. Nothing in it needed judgment, and handing it
to a model cost a call per donor and let the confidence drift (a vacant address with
no forwarding lookup was once scored 1.0 by the model, so the run never paused for a
human). Written as code it is the same table, testable, and identical on every run.

Confidence is certainty about the deliverability VERDICT, which is what
route_after_address gates on: a certain "deliverable" flows on, a certain
"undeliverable" ends the run (nothing to mail, nothing for a human to add), and an
uncertain verdict pauses for a person. A vacant address with no forwarding record is
a certain "undeliverable"; a donor who moved with no forwarding address, or with no
address on file at all, is genuinely unknown and goes to a human."""

CONF_CLEAN = 0.95
CONF_PO_BOX = 0.90  # legitimate and deliverable, noted as a mild caution
CONF_CERTAIN_UNDELIVERABLE = 0.95
CONF_MOVED_UNKNOWN = 0.20
CONF_NO_ADDRESS = 0.05


def assess_address(raw: dict, forwarding: dict | None, has_address: bool) -> dict:
    """Returns the AddressResult fields. `raw` is the Address MCP verification,
    `forwarding` the forwarding lookup (only fetched when `raw['moved']`)."""
    if not has_address:
        return _result(False, CONF_NO_ADDRESS, None, False, ["No address on file for this donor."])

    if raw.get("moved"):
        found = bool(forwarding and forwarding.get("found") and forwarding.get("new_address"))
        if found:
            confidence = max(0.0, min(1.0, float(forwarding.get("confidence") or 0.0)))
            return _result(
                True, confidence, forwarding["new_address"], True,
                ["The address on file is no longer current: the donor has moved.",
                 f"A forwarding address was found with match confidence {confidence:.2f}; "
                 "the assessment carries that confidence rather than rounding it up."],
            )
        return _result(
            False, CONF_MOVED_UNKNOWN, None, True,
            ["The donor has moved and no forwarding address was found.",
             "Where they went is unknown, so a person should look."],
        )

    if raw.get("vacant") or not raw.get("valid"):
        why = "vacant" if raw.get("vacant") else "not a valid address"
        return _result(False, CONF_CERTAIN_UNDELIVERABLE, None, False,
                       [f"The address on file is {why}.", "Nothing can be mailed to it."])

    if not raw.get("deliverable"):
        return _result(False, CONF_CERTAIN_UNDELIVERABLE, None, False,
                       ["The address is valid but not deliverable.", "Nothing can be mailed to it."])

    standardized = raw.get("standardized_address")
    if raw.get("po_box"):
        return _result(True, CONF_PO_BOX, standardized, False,
                       ["Valid and deliverable.", "It is a PO box: legitimate, noted as a mild caution."])
    return _result(True, CONF_CLEAN, standardized, False, ["Valid, deliverable and unchanged."])


def _result(deliverable: bool, confidence: float, updated: str | None, moved: bool, reasoning: list[str]) -> dict:
    return {
        "deliverable": deliverable,
        "confidence": confidence,
        "updated_address": updated,
        "moved": moved,
        "reasoning": reasoning,
    }
