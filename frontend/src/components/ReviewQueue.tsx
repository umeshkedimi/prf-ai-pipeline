import { useEffect, useState } from "react";
import { listReviews } from "../api";
import type { ReviewStatus, WorkflowReviewSummary } from "../types";
import { StatusBadge } from "./StatusBadge";

const PAGE_SIZE = 20;

export function ReviewQueue({ onSelect }: { onSelect: (id: string) => void }) {
  const [status, setStatus] = useState<ReviewStatus | "all">("all");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<WorkflowReviewSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    listReviews(status, PAGE_SIZE, offset)
      .then(setRows)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [status, offset]);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <label>
          Queue:{" "}
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as ReviewStatus | "all");
              setOffset(0);
            }}
          >
            <option value="all">All (awaiting + needs review)</option>
            <option value="awaiting_review">Awaiting review (blocking)</option>
            <option value="needs_review">Needs review (advisory)</option>
          </select>
        </label>
      </div>

      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : rows.length === 0 ? (
        <p>Nothing in this queue.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
              <th>Donor</th>
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
