import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { getCampaign, ingestDonorsCsv, listAgentRuns, startAgentRun } from "../api";
import type { AgentRunRead, CampaignSummary, DonorIngestResult } from "../types";
import { StatusBadge } from "./StatusBadge";

export function CampaignDetail({
  id,
  isAdmin,
  onBack,
  onOpenAgentRun,
}: {
  id: string;
  isAdmin: boolean;
  onBack: () => void;
  onOpenAgentRun: (id: string) => void;
}) {
  const [campaign, setCampaign] = useState<CampaignSummary | null>(null);
  const [runs, setRuns] = useState<AgentRunRead[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [ingest, setIngest] = useState<DonorIngestResult | null>(null);

  const [maxRuns, setMaxRuns] = useState("200");
  const [maxSteps, setMaxSteps] = useState("40");
  const [starting, setStarting] = useState(false);

  const load = () => {
    Promise.all([getCampaign(id), listAgentRuns(id)])
      .then(([c, r]) => {
        setCampaign(c);
        setRuns(r);
      })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(load, [id]);

  const handleUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      setIngest(await ingestDonorsCsv(file, id));
      setFile(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    try {
      const run = await startAgentRun(id, {
        max_runs: Number(maxRuns),
        max_steps: Number(maxSteps),
      });
      onOpenAgentRun(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  if (!campaign) return <p>{error ?? "Loading…"}</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <button type="button" onClick={onBack}>
          ← Campaigns
        </button>
        <h2 style={{ marginBottom: 4 }}>{campaign.name}</h2>
        <span>
          {campaign.total_donors} donors{campaign.appeal_code ? ` · ${campaign.appeal_code}` : ""}
        </span>
      </div>
      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}

      <section>
        <h3>Donor status</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {Object.entries(campaign.donor_counts).map(([status, n]) => (
            <div key={status} style={{ border: "1px solid #a8a29e", borderRadius: 6, padding: "6px 12px" }}>
              <div style={{ fontSize: "1.3rem", fontWeight: 700 }}>{n}</div>
              <div style={{ fontSize: "0.8rem" }}>{status}</div>
            </div>
          ))}
        </div>
      </section>

      {isAdmin && (
        <section>
          <h3>Upload donors to this campaign</h3>
          <form onSubmit={handleUpload} style={{ display: "flex", gap: 8 }}>
            <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button type="submit" disabled={!file || uploading}>
              {uploading ? "Uploading…" : "Upload CSV"}
            </button>
          </form>
          {ingest && (
            <p>
              {ingest.rows_inserted} inserted, {ingest.rows_updated} updated, {ingest.rows_rejected} rejected.
              Uploading only stages donors; nothing runs until you start the agent.
            </p>
          )}
        </section>
      )}

      {isAdmin && (
        <section>
          <h3>Campaign agent</h3>
          <p style={{ marginTop: 0 }}>
            The agent profiles the list, fixes what it can (with your approval), launches donor runs in
            batches, and reports what is ready and why anything is held. It stops at its budget.
          </p>
          <div style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
            <label>
              Max donor runs
              <br />
              <input value={maxRuns} onChange={(e) => setMaxRuns(e.target.value)} size={6} />
            </label>
            <label>
              Max steps
              <br />
              <input value={maxSteps} onChange={(e) => setMaxSteps(e.target.value)} size={6} />
            </label>
            <button type="button" onClick={handleStart} disabled={starting || campaign.total_donors === 0}>
              {starting ? "Starting…" : "Prepare campaign for mailing"}
            </button>
          </div>
        </section>
      )}

      <section>
        <h3>Agent runs</h3>
        {runs.length === 0 ? (
          <p>None yet.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            {runs.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => onOpenAgentRun(r.id)} style={{ width: "100%", textAlign: "left" }}>
                  <StatusBadge status={r.status} /> {new Date(r.created_at).toLocaleString()} · {r.budget.steps}{" "}
                  steps · {r.budget.runs} donor runs
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
