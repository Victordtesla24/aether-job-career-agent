import React from "react";

/** The one KPI tile. The magnitude is typeset; the unit rides small and raised. */
export function StatBlock({ label, value, unit, note, delta = null, visual, className = "", style, children }) {
  const unmeasured = value === null || value === undefined || value === "—";
  return (
    <div
      className={"elev-1 " + className}
      style={{ position: "relative", overflow: "hidden", borderRadius: "var(--radius-2xl)", padding: 20, ...style }}
    >
      <p className="type-section" style={{ margin: 0, paddingRight: 52 }}>{label}</p>
      {delta !== null && delta !== 0 ? (
        <span
          className="type-mono-micro"
          style={{
            position: "absolute",
            right: 18,
            top: 18,
            borderRadius: "var(--radius-full)",
            border: "1px solid " + (delta > 0 ? "rgba(111,175,141,0.32)" : "rgba(200,135,58,0.32)"),
            background: delta > 0 ? "rgba(111,175,141,0.10)" : "rgba(200,135,58,0.10)",
            color: delta > 0 ? "var(--state-ok)" : "var(--state-warn)",
            padding: "2px 7px",
            fontWeight: 600
          }}
        >
          {delta > 0 ? "+" + delta : delta}
        </span>
      ) : null}
      <div
        className="mono"
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 2,
          marginTop: 12,
          fontSize: 32,
          fontWeight: 500,
          lineHeight: 1,
          letterSpacing: "-0.02em",
          color: unmeasured ? "var(--state-neutral)" : "var(--text-primary)"
        }}
      >
        {children ?? (unmeasured ? "—" : value)}
        {unit ? (
          <span style={{ transform: "translateY(-0.55em)", fontSize: 14, fontWeight: 500, color: "var(--text-secondary)" }}>{unit}</span>
        ) : null}
      </div>
      {note ? <p className="type-meta" style={{ margin: "10px 0 0" }}>{note}</p> : null}
      {visual ? <div style={{ marginTop: 12 }}>{visual}</div> : null}
    </div>
  );
}
