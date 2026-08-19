import { useEffect, useState } from "react";
import { listRuns } from "../api";
import type { RunStatus, WorkflowRunSummary } from "../types";
import { StatusBadge } from "./StatusBadge";

const PAGE_SIZE = 20;

export function RunHistory({ onSelect }: { onSelect: (id: string) => void }) {
  const [status, setStatus] = useState<RunStatus | "all">("all");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<WorkflowRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    listRuns(status, PAGE_SIZE, offset)
      .then(setRows)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [status, offset]);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <label>
          Status:{" "}
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as RunStatus | "all");
              setOffset(0);
            }}
          >
            <option value="all">All statuses</option>
            <option value="completed">Completed</option>
            <option value="needs_review">Needs review</option>
            <option value="awaiting_review">Awaiting review</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
            <option value="failed">Failed</option>
          </select>
        </label>
      </div>

      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : rows.length === 0 ? (
        <p>No runs match this filter.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
              <th>Donor</th>
              <th>Donor ID</th>
              <th>Campaign</th>
              <th>Status</th>
              <th>Stage</th>
              <th>Confidence</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => onSelect(row.id)}
                style={{ cursor: "pointer", borderBottom: "1px solid #eee" }}
              >
                <td>{row.donor_name}</td>
                <td>{row.donor_external_id ?? row.donor_id}</td>
                <td>{row.campaign_name ?? "—"}</td>
                <td>
                  <StatusBadge status={row.status} />
                </td>
                <td>{row.pending_review?.stage ?? row.current_agent ?? "—"}</td>
                <td>{row.confidence ?? "—"}</td>
                <td>{new Date(row.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Previous
        </button>
        <button disabled={rows.length < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Next
        </button>
      </div>
    </div>
  );
}
