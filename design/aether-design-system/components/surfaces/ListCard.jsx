import React from "react";

/** A selectable list row / result card. Selection is a gold rail, never a wash. */
export function ListCard({ selected = false, interactive = true, onClick, as: Tag = "div", className = "", style, children }) {
  const isButton = interactive && onClick;
  const El = isButton ? "button" : Tag;
  return (
    <El
      className={(selected ? "elev-2 " : "elev-1 ") + className}
      type={isButton ? "button" : undefined}
      onClick={onClick}
      aria-current={selected ? "true" : undefined}
      style={{
        position: "relative",
        display: "block",
        width: "100%",
        overflow: "hidden",
        textAlign: "left",
        borderRadius: "var(--radius-xl)",
        padding: 14,
        borderColor: selected ? "var(--gold-border-strong)" : undefined,
        cursor: interactive ? "pointer" : "default",
        transition: "border-color var(--dur-fast) var(--ease),background-color var(--dur-fast) var(--ease)",
        ...style
      }}
      onMouseEnter={(e) => { if (interactive && !selected) e.currentTarget.style.borderColor = "var(--hairline-strong)"; }}
      onMouseLeave={(e) => { if (interactive && !selected) e.currentTarget.style.borderColor = ""; }}
    >
      {selected ? (
        <span
          aria-hidden="true"
          style={{ position: "absolute", left: 0, top: "50%", transform: "translateY(-50%)", width: 3, height: 22, borderRadius: "0 2px 2px 0", background: "linear-gradient(180deg,var(--gold-pale),var(--gold-dark))" }}
        />
      ) : null}
      {children}
    </El>
  );
}
