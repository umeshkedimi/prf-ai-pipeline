const COLORS: Record<string, string> = {
  awaiting_review: "#b45309",
  needs_review: "#b45309",
  completed: "#15803d",
  failed: "#b91c1c",
  running: "#1d4ed8",
  pending: "#57534e",
};

export function StatusBadge({ status }: { status: string }) {
  const color = COLORS[status] ?? "#57534e";
  return (
    <span
      style={{
        color,
        border: `1px solid ${color}`,
        borderRadius: 4,
        padding: "2px 8px",
        fontSize: "0.8rem",
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {status}
    </span>
  );
}
