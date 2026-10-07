"""Builds the final report from facts, not from the model's prose. The model's own
summary is included verbatim but labelled as such; every number comes from the
database or the audit trail."""

from typing import Any


def summarize_steps(steps: list[dict[str, Any]]) -> dict:
    """steps: agent_steps rows as dicts (tool, tier, args, outcome, observation), in seq order."""
    proposals, actions, decisions, duplicate_holds = [], [], [], []
    refused = {"denied": 0, "invalid_args": 0, "error": 0, "needs_approval": 0}
    for st in steps:
        tool, tier, outcome = st["tool"], st.get("tier"), st["outcome"]
        if tool == "human_decision":
            decisions.append({"tool": (st.get("args") or {}).get("tool"), **(st.get("observation") or {})})
        elif outcome == "ok" and tier == "propose":
            a = st.get("args") or {}
            proposals.append({"kind": a.get("kind"), "donor_external_ids": a.get("donor_external_ids", []),
                              "reason": a.get("reason")})
        elif outcome == "ok" and tier in {"act", "irreversible"}:
            obs = st.get("observation") or {}
            for sk in obs.get("skipped", []) if isinstance(obs, dict) else []:
                reason = sk.get("reason", "")
                if reason.startswith("probable_duplicate_of_"):
                    duplicate_holds.append({"external_id": sk.get("external_id"),
                                            "duplicate_of": reason.removeprefix("probable_duplicate_of_")})
            actions.append({"tool": tool, "tier": tier, **{k: obs[k] for k in ("launched", "changed") if k in obs}})
        elif outcome in refused:
            refused[outcome] += 1
    return {"proposals": proposals, "actions": actions, "human_decisions": decisions,
            "duplicate_holds": _dedupe(duplicate_holds), "refused_calls": refused, "steps": len(steps)}


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = it.get("external_id")
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def decide_final_status(base_status: str, unresolved: dict) -> str:
    """`completed` means the work is done. If the agent stopped talking while donors were
    still in flight or unaddressed, saying "completed" would be the one dishonest word in
    an otherwise fact-built report, so the status says there are gaps."""
    if base_status == "completed" and (unresolved.get("in_flight") or unresolved.get("staged_unaddressed")):
        return "completed_with_gaps"
    return base_status
