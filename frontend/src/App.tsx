import { useEffect, useState } from "react";
import { ReviewQueue } from "./components/ReviewQueue";
import { RunDetail } from "./components/RunDetail";
import { NewRunForm } from "./components/NewRunForm";
import { Login } from "./components/Login";
import { clearToken, getCurrentUser, getToken } from "./api";
import type { UserRead } from "./types";
import "./App.css";

function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lookupId, setLookupId] = useState("");
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
        </div>
      )}

      {selectedId ? (
        <RunDetail id={selectedId} onBack={() => setSelectedId(null)} />
      ) : (
        <ReviewQueue onSelect={setSelectedId} />
      )}
    </div>
  );
}

export default App;
