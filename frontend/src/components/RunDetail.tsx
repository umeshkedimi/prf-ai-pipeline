import { useCallback, useEffect, useState } from "react";
import { fetchWorkflowPdf, getWorkflowRun, submitReview } from "../api";
import type { WorkflowRunRead } from "../types";
import { StatusBadge } from "./StatusBadge";
import { ReviewDecisionForm } from "./ReviewDecisionForm";
import { ResultCard } from "./ResultCard";

export function RunDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [run, setRun] = useState<WorkflowRunRead | null>(null);
  const [verbose, setVerbose] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);

  const handleViewPdf = async () => {
    setPdfError(null);
    try {
      const blob = await fetchWorkflowPdf(id);
      window.open(URL.createObjectURL(blob), "_blank", "noreferrer");
    } catch (err) {
      setPdfError((err as Error).message);
    }
  };

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

  const pdfResult = run.result?.pdf_generation as
    | {
        reference: string;
        tracking_number: string | null;
        postage_class: string | null;
        held?: boolean;
        hold_reason?: string[];
      }
    | undefined;

  return (
    <div>
      <button onClick={onBack}>← Back to queue</button>
      <button onClick={load} disabled={loading} style={{ marginLeft: 8 }}>
        {loading ? "Refreshing…" : "Refresh"}
      </button>
      <h2 style={{ marginTop: 12 }}>
        Run {run.id} <StatusBadge status={run.status} />
      </h2>
      <p>
        Donor: {run.donor_external_id ?? run.donor_id} · Current agent: {run.current_agent ?? "—"} ·
        Confidence: {run.confidence ?? "—"}
      </p>
      <p>
        Created {new Date(run.created_at).toLocaleString()}
        {run.completed_at && ` · Completed ${new Date(run.completed_at).toLocaleString()}`}
      </p>
      {run.error && <p style={{ color: "#b91c1c" }}>Error: {run.error}</p>}

      {pdfResult && (
        <p>
          {pdfResult.held ? (
            <>
              Letter generated but <strong>held — not sent to print</strong>, ref{" "}
              <strong>{pdfResult.reference}</strong>.{" "}
            </>
          ) : (
            <>
              Letter generated — ref <strong>{pdfResult.reference}</strong>, tracking{" "}
              {pdfResult.tracking_number} ({pdfResult.postage_class}).{" "}
            </>
          )}
          <button type="button" onClick={handleViewPdf}>
            View PDF
          </button>
          {pdfError && <span style={{ color: "#b91c1c", marginLeft: 8 }}>{pdfError}</span>}
        </p>
      )}

      {run.status === "needs_review" && (
        <p
          style={{
            background: "var(--warn-bg)",
            color: "var(--warn-text)",
            border: "1px solid var(--warn-border)",
            borderRadius: 6,
            padding: 12,
          }}
        >
          <strong>Advisory only — nothing to approve or reject here.</strong> The pipeline already
          reached a final state (nothing is paused).{" "}
          {run.current_agent === "pdf_generation" ? (
            <>
              PDF generation itself has no confidence of its own — it rendered the letter but{" "}
              <strong>held it back from the print vendor</strong> because the{" "}
              <strong>Compliance</strong> review disapproved the letter's wording, even after
              automatic rewrites. See the Compliance card below for what it flagged.
            </>
          ) : (
            <>
              A low-confidence outcome at <strong>{run.current_agent}</strong> flagged it for a human
              to glance at. Check the results below for what triggered it.
            </>
          )}
        </p>
      )}

      {run.result && Object.keys(run.result).length > 0 && (
        <section style={{ display: "flex", flexDirection: "column", gap: 8, margin: "16px 0" }}>
          <h3>Results</h3>
          {Object.entries(run.result).map(([key, data]) => (
            <ResultCard key={key} stepKey={key} data={data as Record<string, unknown>} />
          ))}
        </section>
      )}

      {run.status === "awaiting_review" && run.pending_review && (
        <section style={{ border: "1px solid #ccc", borderRadius: 6, padding: 12, margin: "16px 0" }}>
          <h3>Blocked on: {run.pending_review.reason}</h3>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              background: "var(--code-bg)",
              color: "var(--code-text)",
              padding: 8,
              borderRadius: 4,
            }}
          >
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
