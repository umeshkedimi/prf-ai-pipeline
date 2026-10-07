import { useEffect, useState } from "react";
import { ReviewQueue } from "./components/ReviewQueue";
import { RunHistory } from "./components/RunHistory";
import { RunDetail } from "./components/RunDetail";
import { NewRunForm } from "./components/NewRunForm";
import { Login } from "./components/Login";
import { DonorImport } from "./components/DonorImport";
import { Campaigns } from "./components/Campaigns";
import { CampaignDetail } from "./components/CampaignDetail";
import { AgentRunView } from "./components/AgentRunView";
import { clearToken, getCurrentUser, getToken } from "./api";
import type { UserRead } from "./types";
import "./App.css";

type View = "queue" | "history" | "donors" | "campaigns";

function App() {
  const [view, setView] = useState<View>("queue");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lookupId, setLookupId] = useState("");
  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [agentRunId, setAgentRunId] = useState<string | null>(null);
  const [user, setUser] = useState<UserRead | null>(null);
  const [checkedAuth, setCheckedAuth] = useState(false);

  const refreshUser = () => {
    if (!getToken()) {
      setUser(null);
      setCheckedAuth(true);
      return;
    }
    getCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setCheckedAuth(true));
  };

  useEffect(refreshUser, []);

  if (!checkedAuth) return null;

  if (!user) {
    return <Login onLoggedIn={refreshUser} />;
  }

  const handleLogout = () => {
    clearToken();
    setUser(null);
    setSelectedId(null);
  };

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h1>PRF AI Pipeline — Review Dashboard</h1>
        <div style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
          <span>
            {user.full_name} <em>({user.role})</em>
          </span>
          <button type="button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </div>

      {!selectedId && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
          <NewRunForm onStarted={setSelectedId} />
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (lookupId) setSelectedId(lookupId);
            }}
            style={{ display: "flex", gap: 8 }}
          >
            <input
              value={lookupId}
              onChange={(e) => setLookupId(e.target.value)}
              placeholder="jump to a run by id"
            />
            <button type="submit">View</button>
          </form>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              onClick={() => setView("queue")}
              disabled={view === "queue"}
            >
              Review queue
            </button>
            <button
              type="button"
              onClick={() => setView("history")}
              disabled={view === "history"}
            >
              All runs
            </button>
            <button
              type="button"
              onClick={() => setView("donors")}
              disabled={view === "donors"}
            >
              Donors
            </button>
            <button
              type="button"
              onClick={() => setView("campaigns")}
              disabled={view === "campaigns"}
            >
              Campaigns
            </button>
          </div>
        </div>
      )}

      {selectedId ? (
        <RunDetail id={selectedId} onBack={() => setSelectedId(null)} />
      ) : view === "campaigns" && agentRunId ? (
        <AgentRunView id={agentRunId} onBack={() => setAgentRunId(null)} />
      ) : view === "campaigns" && campaignId ? (
        <CampaignDetail
          id={campaignId}
          isAdmin={user.role === "admin"}
          onBack={() => setCampaignId(null)}
          onOpenAgentRun={setAgentRunId}
        />
      ) : view === "campaigns" ? (
        <Campaigns isAdmin={user.role === "admin"} onSelect={setCampaignId} />
      ) : view === "donors" ? (
        <DonorImport isAdmin={user.role === "admin"} onViewRun={setSelectedId} />
      ) : view === "history" ? (
        <RunHistory onSelect={setSelectedId} />
      ) : (
        <ReviewQueue onSelect={setSelectedId} />
      )}
    </div>
  );
}

export default App;
