import { useCallback, useEffect, useState } from "react";
import { getWorkflowRun, submitReview } from "../api";
import type { WorkflowRunRead } from "../types";
import { StatusBadge } from "./StatusBadge";
import { ReviewDecisionForm } from "./ReviewDecisionForm";

export function RunDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [run, setRun] = useState<WorkflowRunRead | null>(null);
  const [verbose, setVerbose] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getWorkflowRun(id, verbose)
      .then(setRun)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id, verbose]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !run) return <p>Loading…</p>;
  if (error) return <p style={{ color: "#b91c1c" }}>{error}</p>;
  if (!run) return null;

  return (
    <div>
      <button onClick={onBack}>← Back to queue</button>
      <h2 style={{ marginTop: 12 }}>
        Run {run.id} <StatusBadge status={run.status} />
      </h2>
      <p>
        Donor: {run.donor_id} · Current agent: {run.current_agent ?? "—"} · Confidence:{" "}
        {run.confidence ?? "—"}
      </p>
      <p>
        Created {new Date(run.created_at).toLocaleString()}
        {run.completed_at && ` · Completed ${new Date(run.completed_at).toLocaleString()}`}
      </p>
      {run.error && <p style={{ color: "#b91c1c" }}>Error: {run.error}</p>}

      {run.status === "awaiting_review" && run.pending_review && (
        <section style={{ border: "1px solid #ccc", borderRadius: 6, padding: 12, margin: "16px 0" }}>
          <h3>Blocked on: {run.pending_review.reason}</h3>
          <pre style={{ whiteSpace: "pre-wrap", background: "#f5f5f4", padding: 8 }}>
            {JSON.stringify(run.pending_review.under_review, null, 2)}
          </pre>
          <ReviewDecisionForm
            stage={run.pending_review.stage}
            onSubmit={async (decision) => {
              await submitReview(id, decision);
              setMessage(
                "Decision submitted — resuming asynchronously via Celery. Refresh in a moment for the new status.",
              );
              load();
            }}
          />
        </section>
      )}

      {message && <p style={{ color: "#1d4ed8" }}>{message}</p>}

      <section style={{ margin: "16px 0" }}>
        <h3>Review history</h3>
        {run.review_history.length === 0 ? (
          <p>No human decisions on this run yet.</p>
        ) : (
          <ul>
            {run.review_history.map((entry, i) => (
              <li key={i}>
                <strong>{entry.stage}</strong>: {entry.action} by {entry.reviewer ?? "unknown"} —{" "}
                {new Date(entry.created_at).toLocaleString()}
                {entry.notes && <div style={{ color: "#57534e" }}>"{entry.notes}"</div>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <button onClick={() => setVerbose((v) => !v)}>
          {verbose ? "Hide" : "Show"} full agent audit trail
        </button>
        {verbose && (
          <ul style={{ marginTop: 8 }}>
            {run.audit_log.map((entry, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                <strong>{entry.step}</strong> ({entry.model ?? "deterministic"}, {entry.latency_ms ?? "?"}ms)
                {entry.confidence !== null && ` — confidence ${entry.confidence}`}
                {entry.reasoning && <div style={{ color: "#57534e" }}>{entry.reasoning}</div>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
