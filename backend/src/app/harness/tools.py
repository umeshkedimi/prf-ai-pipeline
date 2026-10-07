from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class Tier(StrEnum):
    READ = "read"  # observes; free
    PROPOSE = "propose"  # records a suggestion; no side effect on donors or runs
    ACT = "act"  # has an effect, reversible or cheap; charged against budgets
    IRREVERSIBLE = "irreversible"  # mailing, discarding, bulk edits: needs a human


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    tier: Tier
    args_model: type[BaseModel]
    fn: Callable[[Any], Awaitable[Any]]
    timeout_s: float = 30.0
    # Donor runs this call would launch; checked against the run budget BEFORE executing.
    run_cost: Callable[[Any], int] | None = None
    # Runs after argument validation and BEFORE the approval gate. Returns an error
    # message to refuse the call, or None. A request the system can already tell is
    # wrong must never reach a human: it wastes their attention and trains them to
    # approve without reading.
    precheck: Callable[[Any], Awaitable[str | None]] | None = None

    def __post_init__(self) -> None:
        # Unknown keys must be rejected, never silently dropped: a model that passes
        # `approved: true` (or any other field the tool doesn't declare) gets an
        # error back, not a quietly ignored argument.
        if self.args_model.model_config.get("extra") != "forbid":
            raise ValueError(f"{self.name}: args_model must set ConfigDict(extra='forbid')")
