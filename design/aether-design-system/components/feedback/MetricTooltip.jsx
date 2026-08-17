import React from "react";

/** A measured value with the "what is actually counted" disclosure attached. */
export function MetricTooltip({ value, tooltip, className = "", style }) {
  const [open, setOpen] = React.useState(false);
  return (
    <span className={className} style={{ position: "relative", display: "inline-flex", ...style }}>
      <button
        type="button"
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        style={{
          border: 0,
          background: "transparent",
          padding: 0,
          font: "inherit",
          color: "inherit",
          cursor: "help",
          borderBottom: "1px dotted var(--gold-border-strong)"
        }}
      >
        {value}
      </button>
      {open ? (
        <span
          role="tooltip"
          className="elev-3"
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            left: 0,
            zIndex: 40,
            width: 264,
            borderRadius: "var(--radius-lg)",
            padding: "10px 12px",
            fontFamily: "var(--font-body)",
            fontSize: 11.5,
            lineHeight: 1.55,
            fontWeight: 400,
            letterSpacing: 0,
            textTransform: "none",
            color: "var(--text-secondary)"
          }}
        >
          {tooltip}
        </span>
      ) : null}
    </span>
  );
}
