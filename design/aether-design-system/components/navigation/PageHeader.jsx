import React from "react";

/** The one page header: display title, subtitle, action slot, control row. */
export function PageHeader({ title, subtitle, action, controls, footnote, ornament = false, className = "", style }) {
  return (
    <header className={className} style={{ marginBottom: 22, ...style }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between", gap: "8px 16px" }}>
        <div style={{ minWidth: 0 }}>
          <h1 className="type-page" style={{ margin: 0, color: "var(--text-primary)" }}>{title}</h1>
          {subtitle ? <p className="type-page-sub" style={{ margin: "8px 0 0", maxWidth: "68ch" }}>{subtitle}</p> : null}
        </div>
        {action ? <div style={{ display: "flex", flexShrink: 0, alignItems: "center", gap: 10 }}>{action}</div> : null}
      </div>
      {ornament ? (
        <div aria-hidden="true" style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14 }}>
          <span style={{ height: 1, width: 56, background: "linear-gradient(90deg,transparent,var(--gold-border-strong))" }} />
          <span style={{ width: 6, height: 6, transform: "rotate(45deg)", border: "1px solid rgba(201,168,76,0.55)" }} />
          <span style={{ height: 1, flex: 1, background: "linear-gradient(90deg,var(--gold-border),transparent)" }} />
        </div>
      ) : null}
      {controls ? <div style={{ marginTop: 16 }}>{controls}</div> : null}
      {footnote ? <p className="type-meta" style={{ margin: "10px 0 0" }}>{footnote}</p> : null}
    </header>
  );
}
