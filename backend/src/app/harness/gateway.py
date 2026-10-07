import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from app.harness.budget import Budget
from app.harness.tools import Tier, ToolSpec

MAX_OBSERVATION_CHARS = 8000
_PREVIEW_CHARS = 2000


class Outcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    DENIED = "denied"  # unknown tool, or not on this agent's allowlist
    INVALID_ARGS = "invalid_args"
    NEEDS_APPROVAL = "needs_approval"  # irreversible tool, no human approval yet; NOT executed
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class ToolResult:
    outcome: Outcome
    tool: str
    observation: Any
    tier: Tier | None = None
    args: dict = field(default_factory=dict)


@dataclass
class AuditRecord:
    seq: int
    tool: str
    tier: Tier | None
    args: dict
    outcome: Outcome
    observation: Any
    latency_ms: int


AuditSink = Callable[[AuditRecord], Awaitable[None]]


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def _cap(observation: Any) -> Any:
    """A tool result goes back into the model's context; an unbounded one (a
    2,000-row listing) would blow it. Oversized results are replaced by a preview
    and a size, which tells the model to ask for a narrower query."""
    data = _jsonable(observation)
    text = json.dumps(data)
    if len(text) <= MAX_OBSERVATION_CHARS:
        return data
    return {"truncated": True, "chars": len(text), "preview": text[:_PREVIEW_CHARS]}


class ToolGateway:
    """The only path from an agent to a tool. Errors become observations the agent
    can react to; they are never raised into the loop.

    `approved` is a parameter of `call`, not part of the agent's arguments: only the
    code that resumes after a human decision passes it, and tool arg models reject
    unknown keys, so a model cannot supply it."""

    def __init__(
        self,
        tools: list[ToolSpec],
        allowlist: set[str],
        budget: Budget,
        audit: AuditSink | None = None,
        start_seq: int = 0,
    ) -> None:
        self._tools = {t.name: t for t in tools}
        self._allowlist = set(allowlist)
        self.budget = budget
        self._audit = audit
        # Own counter (not budget.steps): human decisions are audited too and must not
        # collide with tool-call seqs. A resumed run passes the last persisted seq.
        self._seq = start_seq

    def describe(self) -> list[dict]:
        """What the model is told it can use: allowlisted tools only."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "tier": t.tier.value,
                "parameters": t.args_model.model_json_schema(),
            }
            for t in self._tools.values()
            if t.name in self._allowlist
        ]

    async def call(self, name: str, args: dict | None = None, *, approved: bool = False) -> ToolResult:
        args = dict(args or {})
        started = time.monotonic()
        spec = self._tools.get(name)

        reason = self.budget.exhausted()
        if reason:
            # Not charged and not audited as a step: the loop is expected to stop.
            return ToolResult(Outcome.BUDGET_EXHAUSTED, name, {"limit": reason}, spec and spec.tier, args)
        self.budget.charge_step()

        result = await self._dispatch(spec, name, args, approved)
        await self._record(result, started)
        return result

    async def _dispatch(self, spec: ToolSpec | None, name: str, args: dict, approved: bool) -> ToolResult:
        if spec is None or name not in self._allowlist:
            allowed = sorted(self._allowlist & set(self._tools))
            return ToolResult(
                Outcome.DENIED, name, {"error": f"tool '{name}' is not available", "available": allowed},
                spec.tier if spec else None, args,
            )
        try:
            parsed = spec.args_model.model_validate(args)
        except ValidationError as exc:
            errors = [f"{'.'.join(map(str, e['loc'])) or '(root)'}: {e['msg']}" for e in exc.errors()]
            return ToolResult(Outcome.INVALID_ARGS, name, {"errors": errors}, spec.tier, args)

        if spec.precheck is not None:
            problem = await spec.precheck(parsed)
            if problem:
                return ToolResult(Outcome.INVALID_ARGS, name, {"errors": [problem]}, spec.tier, args)
        if spec.tier is Tier.IRREVERSIBLE and not approved:
            return ToolResult(
                Outcome.NEEDS_APPROVAL, name,
                {"message": "requires human approval; not executed", "args": args}, spec.tier, args,
            )
        cost = spec.run_cost(parsed) if spec.run_cost else 0
        if cost and self.budget.would_exceed_runs(cost):
            return ToolResult(
                Outcome.BUDGET_EXHAUSTED, name,
                {"limit": "max_runs", "requested": cost, "remaining": self.budget.max_runs - self.budget.runs},
                spec.tier, args,
            )
        try:
            value = await asyncio.wait_for(spec.fn(parsed), timeout=spec.timeout_s)
        except TimeoutError:
            return ToolResult(Outcome.ERROR, name, {"error": f"timed out after {spec.timeout_s}s"}, spec.tier, args)
        except Exception as exc:  # noqa: BLE001 - a tool failure is an observation, not a crash
            return ToolResult(Outcome.ERROR, name, {"error": f"{type(exc).__name__}: {exc}"[:500]}, spec.tier, args)
        # The pre-check above is an upper bound (everything requested). What is charged is
        # what actually happened: a tool that reports `launched` is billed for that.
        actual = value.get("launched", cost) if isinstance(value, dict) else cost
        self.budget.charge_runs(actual if cost else 0)
        return ToolResult(Outcome.OK, name, _cap(value), spec.tier, args)

    async def _record(self, result: ToolResult, started: float) -> None:
        if self._audit is None:
            return
        self._seq += 1
        await self._audit(
            AuditRecord(
                seq=self._seq,
                tool=result.tool,
                tier=result.tier,
                args=_jsonable(result.args),
                outcome=result.outcome,
                observation=result.observation,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        )

    async def log_event(self, tool: str, observation: Any, args: dict | None = None) -> None:
        """Audit something that is not a tool call (e.g. a human's approval decision)
        into the same ordered trajectory. Costs no budget."""
        if self._audit is None:
            return
        self._seq += 1
        await self._audit(
            AuditRecord(
                seq=self._seq, tool=tool, tier=None, args=_jsonable(args or {}),
                outcome=Outcome.OK, observation=_jsonable(observation), latency_ms=0,
            )
        )
