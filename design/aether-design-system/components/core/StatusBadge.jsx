import React from "react";

const TONE = {
  ok: { color: "var(--state-ok)", border: "rgba(111,175,141,0.42)" },
  warn: { color: "var(--state-warn)", border: "rgba(200,135,58,0.42)" },
  danger: { color: "var(--state-danger)", border: "rgba(185,84,75,0.42)" },
  info: { color: "var(--state-info)", border: "rgba(124,147,190,0.42)" },
  neutral: { color: "var(--state-neutral)", border: "var(--hairline-strong)" },
  degraded: { color: "var(--state-degraded)", border: "rgba(160,140,180,0.42)" },
  gold: { color: "var(--gold)", border: "var(--gold-border-strong)" }
};

/** One status badge, seven tones, one shape. The WORD carries the meaning. */
export function StatusBadge({ tone = "neutral", dot = false, live = false, title, className = "", style, children }) {
  const t = TONE[tone] || TONE.neutral;
  return (
    <span
      className={className}
      data-tone={tone}
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        border: "1px solid " + t.border,
        color: t.color,
        borderRadius: "var(--radius-xs)",
        padding: "2px 7px",
        fontFamily: "var(--font-body)",
        fontSize: 10,
        fontWeight: 500,
        letterSpacing: "0.10em",
        textTransform: "uppercase",
        whiteSpace: "nowrap",
        ...style
      }}
    >
      {dot ? (
        <span
          className={live && tone === "ok" ? "pulse-ok" : undefined}
          aria-hidden="true"
          style={{ width: 6, height: 6, borderRadius: "999px", background: "currentColor", flexShrink: 0 }}
        />
      ) : null}
      {children}
    </span>
  );
}
