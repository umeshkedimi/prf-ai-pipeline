import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ingestDonorsCsv, listUnrunDonors, startWorkflowRunBatch } from "../api";
import type { DonorIngestResult, DonorUnrunRead, WorkflowRunBatchItem } from "../types";

export function DonorImport({
  isAdmin,
  onViewRun,
}: {
  isAdmin: boolean;
  onViewRun: (id: string) => void;
}) {
  const [donors, setDonors] = useState<DonorUnrunRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [ingestResult, setIngestResult] = useState<DonorIngestResult | null>(null);

  const [triggering, setTriggering] = useState(false);
  const [batchResult, setBatchResult] = useState<WorkflowRunBatchItem[] | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    listUnrunDonors()
      .then((rows) => {
        setDonors(rows);
        setSelected(new Set());
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setIngestResult(null);
    try {
      const result = await ingestDonorsCsv(file);
      setIngestResult(result);
      setFile(null);
      load();
    } catch (err) {
      setUploadError((err as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleStartRuns = async () => {
    setTriggering(true);
    setBatchResult(null);
    try {
      const result = await startWorkflowRunBatch([...selected]);
      setBatchResult(result);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div>
      {isAdmin && (
        <section style={{ border: "1px solid #ccc", borderRadius: 6, padding: 12, marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Import donors from CSV</h3>
          <p style={{ color: "#57534e", fontSize: 14 }}>
            Columns: <code>external_id, first_name, last_name</code> required; <code>email</code>,{" "}
            <code>address_line1</code>, <code>address_line2</code>, <code>city</code>, <code>state</code>,{" "}
            <code>postal_code</code>, <code>country</code>, <code>do_not_contact</code>, <code>notes</code>{" "}
            optional. Upserts by <code>external_id</code> — never starts a run.
          </p>
          <form onSubmit={handleUpload} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="file"
              accept=".csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <button type="submit" disabled={!file || uploading}>
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </form>
          {uploadError && <p style={{ color: "#b91c1c" }}>{uploadError}</p>}
          {ingestResult && (
            <div style={{ marginTop: 8 }}>
              <p>
                Inserted <strong>{ingestResult.rows_inserted}</strong>, updated{" "}
                <strong>{ingestResult.rows_updated}</strong>, rejected{" "}
                <strong>{ingestResult.rows_rejected}</strong>.
              </p>
              {ingestResult.rejected.length > 0 && (
                <ul>
                  {ingestResult.rejected.map((r) => (
                    <li key={r.row_number} style={{ color: "#b91c1c" }}>
                      row {r.row_number} ({r.external_id ?? "no id"}): {r.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      )}

      <section>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3>Donors not yet run ({donors.length})</h3>
          <button
            onClick={handleStartRuns}
            disabled={selected.size === 0 || triggering}
          >
            {triggering ? "Starting…" : `Start ${selected.size || ""} run${selected.size === 1 ? "" : "s"}`.trim()}
          </button>
        </div>

        {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
        {loading ? (
          <p>Loading…</p>
        ) : donors.length === 0 ? (
          <p>Nothing staged — every known donor has at least one run.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
                <th></th>
                <th>Donor</th>
                <th>Donor ID</th>
                <th>Location</th>
                <th>Added</th>
              </tr>
            </thead>
            <tbody>
              {donors.map((d) => (
                <tr key={d.id} style={{ borderBottom: "1px solid #eee" }}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(d.external_id ?? d.id)}
                      onChange={() => toggle(d.external_id ?? d.id)}
                    />
                  </td>
                  <td>
                    {d.first_name} {d.last_name}
                  </td>
                  <td>{d.external_id ?? d.id}</td>
                  <td>{[d.city, d.state].filter(Boolean).join(", ") || "—"}</td>
                  <td>{new Date(d.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {batchResult && (
          <ul style={{ marginTop: 12 }}>
            {batchResult.map((r) => (
              <li key={r.donor_id} style={{ color: r.status === "error" ? "#b91c1c" : undefined }}>
                {r.donor_id}:{" "}
                {r.status === "enqueued" && r.workflow_run_id ? (
                  <>
                    enqueued —{" "}
                    <a
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        onViewRun(r.workflow_run_id!);
                      }}
                    >
                      view run
                    </a>
                  </>
                ) : (
                  r.error
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
