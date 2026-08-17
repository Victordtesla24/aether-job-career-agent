import React from "react";

const TONE = {
  info: { color: "var(--state-info)", border: "rgba(124,147,190,0.32)", bg: "rgba(124,147,190,0.08)", icon: "fa-solid fa-circle-info" },
  ok: { color: "var(--state-ok)", border: "rgba(111,175,141,0.32)", bg: "rgba(111,175,141,0.08)", icon: "fa-solid fa-circle-check" },
  warn: { color: "var(--state-warn)", border: "rgba(200,135,58,0.32)", bg: "rgba(200,135,58,0.08)", icon: "fa-solid fa-triangle-exclamation" },
  danger: { color: "var(--state-danger)", border: "rgba(185,84,75,0.32)", bg: "rgba(185,84,75,0.08)", icon: "fa-solid fa-circle-exclamation" },
  degraded: { color: "var(--state-degraded)", border: "rgba(160,140,180,0.32)", bg: "rgba(160,140,180,0.08)", icon: "fa-solid fa-circle-half-stroke" },
  gold: { color: "var(--gold)", border: "var(--gold-border)", bg: "rgba(201,168,76,0.07)", icon: "fa-solid fa-crown" }
};

/** An inline notice: widget error, honest degrade, quota warning, confirmation. */
export function InlineNotice({ tone = "info", title, icon, onDismiss, role, className = "", style, children }) {
  const t = TONE[tone] || TONE.info;
  return (
    <div
      role={role || (tone === "danger" ? "alert" : "status")}
      className={className}
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        border: "1px solid " + t.border,
        background: t.bg,
        borderRadius: "var(--radius-lg)",
        padding: "11px 13px",
        ...style
      }}
    >
      <i className={icon || t.icon} style={{ marginTop: 2, fontSize: 12, color: t.color, flexShrink: 0 }} aria-hidden="true" />
      <div style={{ minWidth: 0, flex: 1 }}>
        {title ? (
          <p style={{ margin: 0, fontFamily: "var(--font-body)", fontSize: 12, fontWeight: 600, letterSpacing: "0.04em", color: t.color }}>{title}</p>
        ) : null}
        <div className="type-body" style={{ fontSize: 12.5, marginTop: title ? 4 : 0 }}>{children}</div>
      </div>
      {onDismiss ? (
        <button
          type="button"
          aria-label="Dismiss"
          onClick={onDismiss}
          style={{ border: 0, background: "transparent", color: "var(--text-muted)", cursor: "pointer", padding: 2, lineHeight: 1 }}
        >
          <i className="fa-solid fa-xmark" style={{ fontSize: 11 }} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
