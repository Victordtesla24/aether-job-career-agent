import React from "react";

/** The house rule: line — diamond — line, in gold. Sits under section headings. */
export function OrnamentDivider({ width = 220, align = "center", tone = "gold", className = "", style }) {
  const colour = tone === "gold" ? "rgba(201,168,76,0.55)" : "var(--hairline-strong)";
  const line = tone === "gold" ? "var(--gold-border)" : "var(--hairline)";
  return (
    <div
      className={className}
      role="presentation"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        width: width === "full" ? "100%" : width,
        marginInline: align === "center" ? "auto" : align === "right" ? "auto 0" : "0 auto",
        ...style
      }}
    >
      <span style={{ height: 1, flex: 1, background: "linear-gradient(90deg,transparent," + line + ")" }} />
      <span style={{ width: 7, height: 7, transform: "rotate(45deg)", border: "1px solid " + colour, flexShrink: 0 }} />
      <span style={{ height: 1, flex: 1, background: "linear-gradient(90deg," + line + ",transparent)" }} />
    </div>
  );
}
