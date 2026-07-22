"""Deterministic fixtures standing in for a real charitable-solicitation
compliance/registration system. A nonprofit must be registered to solicit
donations in a given US state before mailing there at all — that's a legal
fact, not a judgment call, so it lives here rather than being left to the LLM."""

ORG_EIN = "84-1234567"

TAX_DEDUCTIBLE_STATEMENT = (
    "No goods or services were provided in exchange for this contribution. "
    "Prairie Rescue Fund is a 501(c)(3) nonprofit organization "
    f"(EIN {ORG_EIN}); your contribution is tax-deductible to the extent allowed by law."
)

# Per-state registration status and any additional disclosure text that state
# requires on mailed solicitations. Not every state is listed — anything absent
# falls through to the benign default below, same convention as the address
# fixtures (a handful of documented test states, benign defaults otherwise).
# FL is deliberately unregistered: it's the fixture the compliance human-review
# interrupt is built to exercise.
_STATE_REQUIREMENTS: dict[str, dict] = {
    "WA": {
        "registered_to_solicit": True,
        "disclosure_text": (
            "Additional information may be obtained from the Washington Secretary "
            "of State's Charities Program at 1-800-332-4483 or www.sos.wa.gov/charities."
        ),
    },
    "FL": {
        "registered_to_solicit": False,
        "disclosure_text": None,
    },
}
_DEFAULT_REQUIREMENTS = {"registered_to_solicit": True, "disclosure_text": None}


def get_disclosure_requirements(state: str) -> dict:
    req = _STATE_REQUIREMENTS.get((state or "").strip().upper(), _DEFAULT_REQUIREMENTS)
    disclosures = [TAX_DEDUCTIBLE_STATEMENT]
    if req["disclosure_text"]:
        disclosures.append(req["disclosure_text"])
    return {
        "registered_to_solicit": req["registered_to_solicit"],
        "required_disclosures": disclosures,
    }
