import { useState } from "react";
import type { FormEvent } from "react";
import { startWorkflowRun } from "../api";

export function NewRunForm({ onStarted }: { onStarted: (id: string) => void }) {
  const [donorId, setDonorId] = useState("d-0001");
  const [campaignId, setCampaignId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const run = await startWorkflowRun({
        donor_id: donorId,
        campaign_id: campaignId || undefined,
      });
      onStarted(run.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input
        value={donorId}
        onChange={(e) => setDonorId(e.target.value)}
        placeholder="donor id (e.g. d-0001)"
      />
      <input
        value={campaignId}
        onChange={(e) => setCampaignId(e.target.value)}
        placeholder="campaign id (optional)"
      />
      <button type="submit" disabled={submitting}>
        {submitting ? "Starting…" : "Start new run"}
      </button>
      {error && <span style={{ color: "#b91c1c" }}>{error}</span>}
    </form>
  );
}
