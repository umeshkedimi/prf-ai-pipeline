import { useEffect, useState } from "react";
import { decideAgentApproval, getAgentRun } from "../api";
import type { AgentFinalReport, AgentRunDetail, AgentStep } from "../types";
import { StatusBadge } from "./StatusBadge";

const ACTIVE = new Set(["running", "awaiting_approval"]);
const POLL_MS = 4000;

const TIER_COLOR: Record<string, string> = {
  read: "#57534e",
  propose: "#1d4ed8",
  act: "#b45309",
  irreversible: "#b91c1c",
};

const OUTCOME_COLOR: Record<string, string> = {
  ok: "#15803d",
  needs_approval: "#b45309",
  denied: "#b91c1c",
  invalid_args: "#b91c1c",
  error: "#b91c1c",
  budget_exhausted: "#b91c1c",
};

function Bar({ label, used, max }: { label: string; used: number; max: number }) {
  const pct = Math.min(100, Math.round((used / Math.max(max, 1)) * 100));
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ fontSize: "0.8rem" }}>
        {label}: {used.toLocaleString()} / {max.toLocaleString()}
      </div>
      <div style={{ background: "#e7e5e4", borderRadius: 4, height: 8 }}>
        <div
          style={{ width: `${pct}%`, height: 8, borderRadius: 4, background: pct > 85 ? "#b91c1c" : "#1d4ed8" }}
        />
      </div>
    </div>
  );
}

function short(value: unknown, limit = 140): string {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (text === undefined) return "";
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function StepRow({ step }: { step: AgentStep }) {
  const isHuman = step.tool === "human_decision";
  return (
    <li style={{ borderLeft: `3px solid ${isHuman ? "#7c3aed" : TIER_COLOR[step.tier ?? "read"]}`, paddingLeft: 10 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ color: "#78716c" }}>#{step.seq}</span>
        <strong>{isHuman ? "human decision" : step.tool}</strong>
        {step.tier && (
          <span style={{ color: TIER_COLOR[step.tier], fontSize: "0.75rem" }}>{step.tier}</span>
        )}
        <span style={{ color: OUTCOME_COLOR[step.outcome] ?? "#57534e", fontSize: "0.8rem", fontWeight: 600 }}>
          {step.outcome}
        </span>
        {step.latency_ms !== null && step.latency_ms > 0 && (
          <span style={{ color: "#78716c", fontSize: "0.75rem" }}>{step.latency_ms} ms</span>
        )}
      </div>
      {step.args && Object.keys(step.args).length > 0 && (
        <div style={{ fontSize: "0.85rem", color: "#57534e" }}>args: {short(step.args)}</div>
      )}
      <details>
        <summary style={{ fontSize: "0.8rem", cursor: "pointer" }}>result</summary>
        <pre style={{ background: "var(--code-bg)", color: "var(--code-text)", padding: 8, overflowX: "auto" }}>
          {JSON.stringify(step.observation, null, 2)}
        </pre>
      </details>
    </li>
  );
}

function Report({ report }: { report: AgentFinalReport }) {
  if (report.error) return <p style={{ color: "#b91c1c" }}>Run failed: {report.error}</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {report.campaign_status_counts && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {Object.entries(report.campaign_status_counts).map(([k, v]) => (
            <div key={k} style={{ border: "1px solid #a8a29e", borderRadius: 6, padding: "4px 10px" }}>
              <strong>{v}</strong> {k}
            </div>
          ))}
        </div>
      )}
      {report.actions && report.actions.length > 0 && (
        <div>
          <strong>Actions taken</strong>
          <ul>
            {report.actions.map((a, i) => (
              <li key={i}>
                {a.tool} ({a.tier}){a.launched !== undefined ? `: launched ${a.launched}` : ""}
                {a.changed !== undefined ? `: changed ${a.changed}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.proposals && report.proposals.length > 0 && (
        <div>
          <strong>Needs a human</strong>
          <ul>
            {report.proposals.map((p, i) => (
              <li key={i}>
                {p.kind}: {p.donor_external_ids.join(", ")} — {p.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.agent_summary && (
        <div>
          <strong>Agent's own summary</strong> <em>(its words, not verified facts)</em>
          <p style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{report.agent_summary}</p>
        </div>
      )}
    </div>
  );
}

export function AgentRunView({ id, onBack }: { id: string; onBack: () => void }) {
  const [run, setRun] = useState<AgentRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0); // bumping it restarts polling after a decision

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = () => {
      getAgentRun(id)
        .then((r) => {
          if (cancelled) return;
          setRun(r);
          if (ACTIVE.has(r.status)) timer = setTimeout(tick, POLL_MS);
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message);
        });
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id, refreshKey]);

  const decide = async (approve: boolean) => {
    if (!run?.pending_approval) return;
    setDeciding(true);
    setError(null);
    try {
      await decideAgentApproval(id, { tool: run.pending_approval.tool, approve, notes: notes || undefined });
      setNotes("");
      setRefreshKey((k) => k + 1);
    } catch (err) {
      // 409: another reviewer already answered, or the pending call changed.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeciding(false);
    }
  };

  if (!run) return <p>{error ?? "Loading…"}</p>;
  const pending = run.pending_approval;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <button type="button" onClick={onBack}>
          ← Campaign
        </button>
        <h2 style={{ marginBottom: 4 }}>
          Campaign agent <StatusBadge status={run.status} />
        </h2>
        <span>{run.goal}</span>
      </div>
      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <Bar label="steps" used={run.budget.steps} max={run.budget.max_steps} />
        <Bar label="tokens" used={run.budget.tokens} max={run.budget.max_tokens} />
        <Bar label="donor runs" used={run.budget.runs} max={run.budget.max_runs} />
      </div>

      {pending && (
        <section style={{ border: "2px solid #b45309", borderRadius: 8, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>The agent is asking permission</h3>
          <p>
            <strong>{pending.tool}</strong> edits donor records permanently. Check the ids below against
            the data before approving.
          </p>
          <pre style={{ background: "var(--code-bg)", color: "var(--code-text)", padding: 8, overflowX: "auto" }}>
            {JSON.stringify(pending.args, null, 2)}
          </pre>
          {pending.rationale && (
            <details>
              <summary>Agent's reasoning</summary>
              <p style={{ whiteSpace: "pre-wrap" }}>{pending.rationale}</p>
            </details>
          )}
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="notes (optional)"
            style={{ width: "100%", boxSizing: "border-box", margin: "8px 0" }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" disabled={deciding} onClick={() => decide(true)}>
              Approve
            </button>
            <button type="button" disabled={deciding} onClick={() => decide(false)}>
              Deny
            </button>
          </div>
        </section>
      )}

      {run.final_report && (
        <section>
          <h3>Report</h3>
          <Report report={run.final_report} />
        </section>
      )}

      <section>
        <h3>Trajectory ({run.steps.length} steps)</h3>
        <ol style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {run.steps.map((s) => (
            <StepRow key={s.seq} step={s} />
          ))}
        </ol>
      </section>
    </div>
  );
}
