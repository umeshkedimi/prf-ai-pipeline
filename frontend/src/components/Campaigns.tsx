import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { createCampaign, listCampaigns } from "../api";
import type { CampaignRead } from "../types";

export function Campaigns({
  isAdmin,
  onSelect,
}: {
  isAdmin: boolean;
  onSelect: (id: string) => void;
}) {
  const [campaigns, setCampaigns] = useState<CampaignRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [appealCode, setAppealCode] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => {
    setLoading(true);
    listCampaigns()
      .then(setCampaigns)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const created = await createCampaign(name.trim(), appealCode.trim());
      setName("");
      setAppealCode("");
      onSelect(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <h2>Campaigns</h2>
      {isAdmin && (
        <form onSubmit={handleCreate} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="new campaign name" />
          <input
            value={appealCode}
            onChange={(e) => setAppealCode(e.target.value)}
            placeholder="appeal code (optional)"
          />
          <button type="submit" disabled={creating || !name.trim()}>
            {creating ? "Creating…" : "Create campaign"}
          </button>
        </form>
      )}
      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : campaigns.length === 0 ? (
        <p>No campaigns yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          {campaigns.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => onSelect(c.id)} style={{ width: "100%", textAlign: "left" }}>
                <strong>{c.name}</strong>
                {c.appeal_code ? ` · ${c.appeal_code}` : ""} <em>({c.status})</em>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
