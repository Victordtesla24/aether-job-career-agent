import React from "react";

const TONE = {
  neutral: { color: "var(--text-secondary)", bg: "rgba(255,255,255,0.04)", border: "var(--hairline)" },
  accent: { color: "var(--gold)", bg: "rgba(201,168,76,0.10)", border: "var(--gold-border)" },
  ok: { color: "var(--state-ok)", bg: "rgba(111,175,141,0.10)", border: "rgba(111,175,141,0.26)" },
  warn: { color: "var(--state-warn)", bg: "rgba(200,135,58,0.10)", border: "rgba(200,135,58,0.26)" },
  danger: { color: "var(--state-danger)", bg: "rgba(185,84,75,0.10)", border: "rgba(185,84,75,0.26)" },
  info: { color: "var(--state-info)", bg: "rgba(124,147,190,0.10)", border: "rgba(124,147,190,0.26)" },
  degraded: { color: "var(--state-degraded)", bg: "rgba(160,140,180,0.10)", border: "rgba(160,140,180,0.26)" }
};

/** Metadata chip: source, freshness, stage, score. Also a filter pill. */
export function Chip({ tone = "neutral", mono = false, icon, selected = false, onClick, title, className = "", style, children }) {
  const t = TONE[tone] || TONE.neutral;
  const Tag = onClick ? "button" : "span";
  return (
    <Tag
      className={(mono ? "mono " : "") + className}
      type={onClick ? "button" : undefined}
      onClick={onClick}
      title={title}
      aria-pressed={onClick ? selected : undefined}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        minWidth: 0,
        border: "1px solid " + (selected ? "var(--gold-border-strong)" : t.border),
        background: selected ? "rgba(201,168,76,0.12)" : t.bg,
        color: selected ? "var(--gold)" : t.color,
        borderRadius: "var(--radius-xs)",
        padding: "3px 8px",
        fontFamily: mono ? "var(--font-mono)" : "var(--font-body)",
        fontSize: 10.5,
        fontWeight: 500,
        lineHeight: 1.4,
        letterSpacing: mono ? 0 : "0.04em",
        cursor: onClick ? "pointer" : "default",
        ...style
      }}
    >
      {icon ? <i className={icon} style={{ fontSize: "0.9em", opacity: 0.85 }} aria-hidden="true" /> : null}
      {children}
    </Tag>
  );
}
