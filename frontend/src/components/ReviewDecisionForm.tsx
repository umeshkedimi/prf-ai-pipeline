import { useState } from "react";
import type { FormEvent } from "react";
import type { PendingReview, ReviewDecisionCreate } from "../types";

export function ReviewDecisionForm({
  stage,
  onSubmit,
}: {
  stage: PendingReview["stage"];
  onSubmit: (decision: ReviewDecisionCreate) => Promise<void>;
}) {
  const [action, setAction] = useState<ReviewDecisionCreate["action"]>("approve");
  const [reviewer, setReviewer] = useState("");
  const [notes, setNotes] = useState("");
  const [updatedAddress, setUpdatedAddress] = useState("");
  const [updatedAskAmount, setUpdatedAskAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const decision: ReviewDecisionCreate = {
        action,
        reviewer: reviewer || undefined,
        notes: notes || undefined,
      };
      if (stage === "address" && action === "modify" && updatedAddress) {
        decision.updated_address = updatedAddress;
      }
      if (stage === "recommendation" && action === "modify" && updatedAskAmount) {
        decision.updated_ask_amount = Number(updatedAskAmount);
      }
      await onSubmit(decision);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 400 }}>
      <label>
        Action:{" "}
        <select value={action} onChange={(e) => setAction(e.target.value as ReviewDecisionCreate["action"])}>
          <option value="approve">Approve</option>
          <option value="modify">Modify</option>
          <option value="reject">Reject</option>
        </select>
      </label>

      {stage === "address" && action === "modify" && (
        <label>
          Updated address:{" "}
          <input value={updatedAddress} onChange={(e) => setUpdatedAddress(e.target.value)} />
        </label>
      )}

      {stage === "recommendation" && action === "modify" && (
        <label>
          Updated ask amount:{" "}
          <input
            type="number"
            step="0.01"
            value={updatedAskAmount}
            onChange={(e) => setUpdatedAskAmount(e.target.value)}
          />
        </label>
      )}

      <label>
        Reviewer: <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
      </label>
      <label>
        Notes:
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
      </label>

      <button type="submit" disabled={submitting}>
        {submitting ? "Submitting…" : "Submit decision"}
      </button>
    </form>
  );
}
