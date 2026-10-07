"""Builds the final report from facts, not from the model's prose. The model's own
summary is included verbatim but labelled as such; every number comes from the
database or the audit trail."""

from typing import Any


def summarize_steps(steps: list[dict[str, Any]]) -> dict:
    """steps: agent_steps rows as dicts (tool, tier, args, outcome, observation), in seq order."""
    proposals, actions, decisions = [], [], []
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
            actions.append({"tool": tool, "tier": tier, **{k: obs[k] for k in ("launched", "changed") if k in obs}})
        elif outcome in refused:
            refused[outcome] += 1
    return {"proposals": proposals, "actions": actions, "human_decisions": decisions,
            "refused_calls": refused, "steps": len(steps)}
