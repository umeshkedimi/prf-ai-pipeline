from typing import Any

from app.db.models import AgentAuditLog
from app.db.session import db_session


async def write_audit_log(
    *,
    workflow_run_id: str,
    agent_name: str,
    step: str,
    input_snapshot: Any = None,
    output: Any = None,
    confidence: float | None = None,
    reasoning: str | None = None,
    source_refs: list | None = None,
    tool_calls: list | None = None,
    model: str | None = None,
    latency_ms: int | None = None,
) -> None:
    async with db_session() as session:
        session.add(
            AgentAuditLog(
                workflow_run_id=workflow_run_id,
                agent_name=agent_name,
                step=step,
                input_snapshot=input_snapshot,
                output=output,
                confidence=confidence,
                reasoning=reasoning,
                source_refs=source_refs,
                tool_calls=tool_calls,
                model=model,
                latency_ms=latency_ms,
            )
        )
        await session.commit()
