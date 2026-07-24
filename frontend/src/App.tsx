import { useState } from "react";
import { ReviewQueue } from "./components/ReviewQueue";
import { RunDetail } from "./components/RunDetail";
import { NewRunForm } from "./components/NewRunForm";
import "./App.css";

function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lookupId, setLookupId] = useState("");

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1>PRF AI Pipeline — Review Dashboard</h1>

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
