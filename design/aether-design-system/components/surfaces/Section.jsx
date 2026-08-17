import React from "react";

/** The one content section: eyebrow, display title, action slot, reserved footnote. */
export function Section({
  eyebrow,
  title,
  subtitle,
  action,
  footnote,
  accent = false,
  as: Tag = "section",
  className = "",
  style,
  bodyStyle,
  children
}) {
  return (
    <Tag
      className={"elev-1 " + className}
      style={{ position: "relative", overflow: "hidden", borderRadius: "var(--radius-2xl)", padding: 20, ...style }}
    >
      {accent ? (
        <span
          aria-hidden="true"
          style={{
            position: "absolute",
            insetInline: 0,
            top: 0,
            height: 1,
            background: "linear-gradient(90deg,var(--gold-border-strong),rgba(201,168,76,0.10),transparent)"
          }}
        />
      ) : null}
      {eyebrow || title || subtitle || action ? (
        <header style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between", gap: "8px 16px", marginBottom: 14 }}>
          <div style={{ minWidth: 0 }}>
            {eyebrow ? <p className="type-eyebrow" style={{ margin: "0 0 6px" }}>{eyebrow}</p> : null}
            {title ? <h3 className="type-card-title" style={{ margin: 0, color: "var(--text-primary)" }}>{title}</h3> : null}
            {subtitle ? <p className="type-page-sub" style={{ margin: "6px 0 0" }}>{subtitle}</p> : null}
          </div>
          {action ? <div style={{ display: "flex", flexShrink: 0, alignItems: "center", gap: 8 }}>{action}</div> : null}
        </header>
      ) : null}
      <div style={bodyStyle}>{children}</div>
      {footnote ? (
        <p className="type-meta" style={{ display: "flex", alignItems: "flex-start", gap: 6, margin: "14px 0 0" }}>
          <i className="fa-solid fa-circle-info" style={{ marginTop: 3, fontSize: 10, color: "var(--gold)", opacity: 0.7 }} aria-hidden="true" />
          <span style={{ minWidth: 0 }}>{footnote}</span>
        </p>
      ) : null}
    </Tag>
  );
}
