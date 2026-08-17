import React from "react";

/** The one tab strip. Active state is a gold underline, never a filled pill. */
export function SegmentedControl({ items, value, onChange, ariaLabel, idPrefix = "seg", size = "md", className = "", style }) {
  const pad = size === "sm" ? "5px 10px 7px" : "7px 14px 9px";
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={className}
      style={{ display: "inline-flex", maxWidth: "100%", flexWrap: "wrap", alignItems: "stretch", gap: 2, borderBottom: "1px solid var(--hairline)", ...style }}
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            id={idPrefix + "-" + item.value}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.value)}
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
              gap: 7,
              padding: pad,
              border: 0,
              background: active ? "rgba(255,255,255,0.04)" : "transparent",
              borderRadius: "var(--radius-sm) var(--radius-sm) 0 0",
              cursor: "pointer",
              fontFamily: "var(--font-body)",
              fontSize: size === "sm" ? 11 : 11.5,
              fontWeight: active ? 600 : 500,
              letterSpacing: "0.10em",
              textTransform: "uppercase",
              color: active ? "var(--text-primary)" : "var(--text-secondary)",
              transition: "color var(--dur-fast) var(--ease),background-color var(--dur-fast) var(--ease)"
            }}
          >
            {item.icon ? <i className={item.icon} style={{ fontSize: 10, color: active ? "var(--gold)" : "inherit" }} aria-hidden="true" /> : null}
            {item.label}
            {typeof item.count === "number" ? (
              <span className="type-mono-micro" style={{ color: active ? "var(--gold)" : "var(--text-muted)" }}>{item.count}</span>
            ) : null}
            {active ? (
              <span aria-hidden="true" style={{ position: "absolute", insetInline: 0, bottom: -1, height: 2, borderRadius: 2, background: "linear-gradient(90deg,var(--gold-dark),var(--gold-pale),var(--gold-dark))" }} />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
