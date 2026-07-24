function titleCase(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ResultCard({ stepKey, data }: { stepKey: string; data: Record<string, unknown> }) {
  const confidence = data.confidence;
  const bullets = (data.reasoning ?? data.rationale) as unknown[] | undefined;

  return (
    <div style={{ border: "1px solid #e5e4e7", borderRadius: 6, padding: 12 }}>
      <h4 style={{ margin: "0 0 4px" }}>
        {titleCase(stepKey)}
        {typeof confidence === "number" && (
          <span style={{ fontWeight: 400, color: "#57534e" }}> — confidence {confidence}</span>
        )}
      </h4>
      {Array.isArray(bullets) && bullets.length > 0 && (
        <ul style={{ margin: "4px 0" }}>
          {bullets.map((line, i) => (
            <li key={i}>{String(line)}</li>
          ))}
        </ul>
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
