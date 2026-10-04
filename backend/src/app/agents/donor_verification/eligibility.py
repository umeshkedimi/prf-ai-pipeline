"""The hard eligibility rules, enforced in code.

do_not_contact and suppression are the two facts that make mailing a donor
wrong regardless of anything else the pipeline thinks. They used to be
enforced only by the synthesize_verdict *prompt* ("eligible MUST be false"),
while route_after_verification's docstring described them as enforced
deterministically — a claim nothing in the code backed. A model that returned
eligible=true for a do-not-contact donor would have carried that donor through
address checks, an ask, a drafted letter and a print order.

Same shape as donation_recommendation's enforce_deterministic_fields: the
model's output is corrected, not rejected, and the deviation is reported so
the audit trail records that the guard — not the model — made the call."""


def blocking_flags(profile: dict) -> list[str]:
    """The CRM flags that make a donor ineligible, read as-is, never inferred."""
    flags = []
    if profile.get("do_not_contact"):
        flags.append("do_not_contact")
    if profile.get("is_suppressed"):
        flags.append("is_suppressed")
    return flags


def enforce_eligibility(profile: dict, verdict: dict) -> tuple[dict, list[str]]:
    """Force `eligible` to False when a blocking CRM flag is set.

    One-directional on purpose: the guard can only *remove* eligibility. The
    flags are the only hard rules; every other ineligibility judgment stays the
    model's, and nothing here ever promotes an ineligible verdict. Confidence is
    left as the model reported it — a guard repairing the answer doesn't make
    the model's assessment more certain."""
    flags = blocking_flags(profile)
    if not flags or not verdict.get("eligible"):
        return verdict, []

    corrected = dict(verdict)
    corrected["eligible"] = False
    corrected["reason"] = (
        f"Ineligible by rule: CRM flag {', '.join(flags)} is set. "
        f"(Model reason before correction: {verdict.get('reason')})"
    )
    return corrected, [f"eligible: model returned True, forced False ({', '.join(flags)} is set)"]
