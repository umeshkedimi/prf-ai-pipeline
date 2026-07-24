function titleCase(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const BULLET_SOURCES = [
  { key: "reasoning", label: null },
  { key: "rationale", label: null },
  // Compliance's own field name for what it flagged -- distinct from
  // reasoning/rationale because it can be non-empty even when reasoning is
  // ([]), and it's the field that actually explains a disapproval.
  { key: "flagged_issues", label: "Flagged issues:" },
] as const;

export function ResultCard({ stepKey, data }: { stepKey: string; data: Record<string, unknown> }) {
  const confidence = data.confidence;
  const source = BULLET_SOURCES.find(
    (s) => Array.isArray(data[s.key]) && (data[s.key] as unknown[]).length > 0,
  );
  const bullets = source ? (data[source.key] as unknown[]) : undefined;

  return (
    <div style={{ border: "1px solid #e5e4e7", borderRadius: 6, padding: 12 }}>
      <h4 style={{ margin: "0 0 4px" }}>
        {titleCase(stepKey)}
        {typeof confidence === "number" && (
          <span style={{ fontWeight: 400, color: "#57534e" }}> — confidence {confidence}</span>
        )}
      </h4>
      {bullets && (
        <>
          {source?.label && <strong>{source.label}</strong>}
          <ul style={{ margin: "4px 0" }}>
            {bullets.map((line, i) => (
              <li key={i}>{String(line)}</li>
            ))}
          </ul>
        </>
      )}
      <details>
        <summary style={{ cursor: "pointer", color: "#57534e" }}>Raw output</summary>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            background: "var(--code-bg)",
            color: "var(--code-text)",
            padding: 8,
            borderRadius: 4,
          }}
        >
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}
