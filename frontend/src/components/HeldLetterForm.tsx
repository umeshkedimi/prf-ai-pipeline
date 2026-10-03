import { useState } from "react";
import type { FormEvent } from "react";
import type { HeldLetterDecision } from "../types";

/** Decision on a letter Compliance disapproved and the pipeline held back from
 * print. A note is required either way: overruling (or confirming) the model's
 * verdict needs a recorded reason. The reviewer's identity is set server-side. */
export function HeldLetterForm({
  holdReason,
  onSubmit,
}: {
  holdReason: string[];
  onSubmit: (decision: HeldLetterDecision) => Promise<void>;
}) {
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = async (action: HeldLetterDecision["action"], e?: FormEvent) => {
    e?.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({ action, notes: notes.trim() });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const noteValid = notes.trim().length >= 3;

  return (
    <section style={{ border: "1px solid #ccc", borderRadius: 6, padding: 12, margin: "16px 0" }}>
      <h3>Held letter — decide</h3>
      <p>
        Compliance disapproved this letter and it has <strong>not</strong> been sent to print.
        Releasing places the print order; discarding closes the run and nothing is ever mailed.
      </p>
      {holdReason.length > 0 && (
        <ul>
          {holdReason.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      <form
        onSubmit={(e) => decide("release", e)}
        style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 400 }}
      >
        <label>
          Reason (required):{" "}
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="submit" disabled={submitting || !noteValid}>
            Release to print
          </button>
          <button type="button" disabled={submitting || !noteValid} onClick={() => decide("discard")}>
            Discard letter
          </button>
        </div>
        {error && <span style={{ color: "#b91c1c" }}>{error}</span>}
      </form>
    </section>
  );
}
