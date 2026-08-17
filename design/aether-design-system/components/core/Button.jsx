import React from "react";

const TONES = {
  primary: {
    background: "linear-gradient(180deg,var(--gold-light),var(--gold-dark))",
    color: "var(--accent-on)",
    border: "1px solid var(--gold-dark)",
    fontWeight: 700
  },
  outline: {
    background: "transparent",
    color: "var(--gold)",
    border: "1px solid var(--gold-border)"
  },
  neutral: {
    background: "rgba(255,255,255,0.045)",
    color: "var(--text-primary)",
    border: "1px solid var(--hairline)"
  },
  quiet: { background: "transparent", color: "var(--text-secondary)", border: "1px solid transparent" },
  ok: { background: "rgba(111,175,141,0.12)", color: "var(--state-ok)", border: "1px solid rgba(111,175,141,0.40)" },
  danger: { background: "rgba(185,84,75,0.12)", color: "var(--state-danger)", border: "1px solid rgba(185,84,75,0.40)" },
  warn: { background: "rgba(200,135,58,0.12)", color: "var(--state-warn)", border: "1px solid rgba(200,135,58,0.40)" },
  info: { background: "rgba(124,147,190,0.12)", color: "var(--state-info)", border: "1px solid rgba(124,147,190,0.40)" }
};

const SIZES = {
  xs: { padding: "4px 10px", fontSize: 11, letterSpacing: "0.10em" },
  sm: { padding: "7px 14px", fontSize: 11.5, letterSpacing: "0.11em" },
  md: { padding: "10px 20px", fontSize: 12, letterSpacing: "0.12em" },
  lg: { padding: "14px 30px", fontSize: 13, letterSpacing: "0.14em" }
};

/** The call-to-action. Gold fill is the ONE primary per surface. */
export function Button({
  tone = "neutral",
  size = "sm",
  icon,
  iconAfter,
  block = false,
  disabled = false,
  href,
  onClick,
  type = "button",
  title,
  className = "",
  style,
  children
}) {
  const Tag = href ? "a" : "button";
  const base = {
    display: block ? "flex" : "inline-flex",
    width: block ? "100%" : undefined,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    fontFamily: "var(--font-body)",
    fontWeight: TONES[tone].fontWeight || 500,
    textTransform: "uppercase",
    borderRadius: "var(--radius-xs)",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
    whiteSpace: "nowrap",
    textDecoration: "none",
    transition: "background-color var(--dur-fast) var(--ease),border-color var(--dur-fast) var(--ease),box-shadow var(--dur) var(--ease),transform var(--dur-fast) var(--ease)",
    ...SIZES[size],
    ...TONES[tone],
    ...style
  };
  const hover = (e, on) => {
    if (disabled) return;
    const el = e.currentTarget;
    el.style.transform = on ? "translateY(-1px)" : "translateY(0)";
    if (tone === "primary") el.style.boxShadow = on ? "0 0 24px rgba(201,168,76,0.35)" : "none";
    if (tone === "outline") el.style.borderColor = on ? "var(--gold-border-strong)" : "var(--gold-border)";
    if (tone === "neutral") el.style.background = on ? "var(--surface-hover)" : "rgba(255,255,255,0.045)";
    if (tone === "quiet") el.style.color = on ? "var(--gold)" : "var(--text-secondary)";
  };
  return (
    <Tag
      className={className}
      style={base}
      href={href}
      onClick={disabled ? undefined : onClick}
      type={href ? undefined : type}
      disabled={href ? undefined : disabled}
      title={title}
      onMouseEnter={(e) => hover(e, true)}
      onMouseLeave={(e) => hover(e, false)}
    >
      {icon ? <i className={icon} style={{ fontSize: "0.9em" }} aria-hidden="true" /> : null}
      {children}
      {iconAfter ? <i className={iconAfter} style={{ fontSize: "0.85em" }} aria-hidden="true" /> : null}
    </Tag>
  );
}
