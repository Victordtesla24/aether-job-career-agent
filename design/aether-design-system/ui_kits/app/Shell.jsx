/* The command-center shell: gold-hairline rail, chrome-blur command bar.
   Recreated from apps/web/src/components/shell/{Rail,CommandBar}.tsx. */
const { useState } = React;

function Rail({ current, onNavigate, collapsed, onToggle }) {
  const { Wordmark, Button, StatusBadge } = window.__DS;
  return (
    <aside
      aria-label="Primary navigation rail"
      style={{
        position: "sticky", top: 0, height: "100vh", flexShrink: 0,
        width: collapsed ? 64 : 248, display: "flex", flexDirection: "column",
        overflowY: "auto", overflowX: "hidden",
        borderRight: "1px solid var(--hairline)", padding: "18px 12px",
        transition: "width var(--dur-slow) var(--ease)"
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22, paddingInline: collapsed ? 0 : 6, justifyContent: collapsed ? "center" : "space-between" }}>
        {collapsed
          ? <Wordmark size="sm" variant="mark" src="../../assets/aether-mark.png" />
          : <Wordmark size="sm" src="../../assets/aether-mark.png" />}
        {collapsed ? null : (
          <button type="button" onClick={onToggle} aria-label="Collapse navigation rail"
            style={{ border: 0, background: "transparent", color: "var(--text-faint)", cursor: "pointer", padding: 4 }}>
            <i className="fa-solid fa-angles-left" style={{ fontSize: 11 }} aria-hidden="true" />
          </button>
        )}
      </div>

      <nav aria-label="Primary" style={{ display: "flex", flexDirection: "column" }}>
        {window.AE_DATA.nav.map((group) => (
          <div key={group.group}>
            {collapsed
              ? <hr style={{ margin: "10px 8px", border: 0, borderTop: "1px solid var(--hairline)" }} />
              : <p className="type-section" style={{ margin: "18px 0 6px", paddingInline: 10 }}>{group.group}</p>}
            {group.items.map((item) => {
              const active = current === item.href;
              return (
                <a key={item.href} href="#" onClick={(e) => { e.preventDefault(); onNavigate(item.href); }}
                  aria-current={active ? "page" : undefined} title={collapsed ? item.label : undefined}
                  style={{
                    position: "relative", display: "flex", alignItems: "center", gap: 12,
                    justifyContent: collapsed ? "center" : "flex-start",
                    padding: collapsed ? "9px 0" : "8px 10px", borderRadius: "var(--radius-md)",
                    fontSize: 12.5, textDecoration: "none",
                    background: active ? "var(--surface-raised)" : "transparent",
                    color: active ? "var(--gold)" : "var(--text-secondary)",
                    fontWeight: active ? 600 : 400,
                    transition: "background-color var(--dur-fast) var(--ease),color var(--dur-fast) var(--ease)"
                  }}
                  onMouseEnter={(e) => { if (!active) { e.currentTarget.style.background = "var(--surface-raised)"; e.currentTarget.style.color = "var(--text-primary)"; } }}
                  onMouseLeave={(e) => { if (!active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-secondary)"; } }}
                >
                  {active ? (
                    <span aria-hidden="true" style={{ position: "absolute", left: 0, top: "50%", transform: "translateY(-50%)", width: 3, height: 20, borderRadius: "0 2px 2px 0", background: "linear-gradient(180deg,var(--gold-pale),var(--gold-dark))" }} />
                  ) : null}
                  <i className={item.icon} style={{ width: 16, textAlign: "center", fontSize: 12.5 }} aria-hidden="true" />
                  {collapsed ? null : <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.label}</span>}
                  {!collapsed && typeof item.count === "number" ? (
                    <span className="type-mono-micro" style={{ color: item.live ? "var(--state-ok)" : "var(--text-faint)" }}>{item.count}</span>
                  ) : null}
                </a>
              );
            })}
          </div>
        ))}
      </nav>

      <div style={{ marginTop: "auto", paddingTop: 20, display: collapsed ? "none" : "flex", flexDirection: "column", gap: 8 }}>
        <div className="elev-2" style={{ borderRadius: "var(--radius-lg)", padding: 12 }}>
          <p style={{ margin: 0, fontSize: 11.5, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>Pro plan</p>
          <p className="type-mono-micro" style={{ margin: "6px 0 0", color: "var(--text-faint)" }}>68/200 runs this period</p>
          <div role="img" aria-label="34% of this period's runs used" style={{ marginTop: 8, height: 2, borderRadius: 2, background: "rgba(255,255,255,0.10)", overflow: "hidden" }}>
            <span style={{ display: "block", height: "100%", width: "34%", background: "linear-gradient(90deg,var(--gold-dark),var(--gold-light))" }} />
          </div>
        </div>
        <div className="elev-1" style={{ borderRadius: "var(--radius-lg)", padding: 12 }}>
          <div style={{ marginBottom: 6 }}>
            <StatusBadge tone="ok" dot live>Agents active</StatusBadge>
          </div>
          <p className="type-meta" style={{ margin: 0 }}>3 of 6 agents running · 1 stalled</p>
          <Button tone="neutral" size="xs" block style={{ marginTop: 10 }} onClick={() => onNavigate("agents")}>Manage agents</Button>
        </div>
        <div className="type-meta" style={{ display: "flex", flexWrap: "wrap", gap: "2px 8px", paddingInline: 4, marginTop: 4 }}>
          <a href="#">Privacy</a><span>·</span><a href="#">Terms</a><span>·</span><span>© 2026 Aether</span>
        </div>
      </div>
    </aside>
  );
}

function CommandBar({ onOpenNav, onNavigate, collapsed, onToggle }) {
  const { Button, StatusBadge } = window.__DS;
  const [q, setQ] = useState("");
  return (
    <header className="chrome-blur" style={{ position: "sticky", top: 0, zIndex: 30, minHeight: 64, display: "flex", alignItems: "center", gap: 14, padding: "0 24px", borderBottom: "1px solid var(--hairline)" }}>
      {collapsed ? (
        <button type="button" onClick={onToggle} aria-label="Expand navigation rail" style={{ border: 0, background: "transparent", color: "var(--text-muted)", cursor: "pointer" }}>
          <i className="fa-solid fa-angles-right" style={{ fontSize: 12 }} aria-hidden="true" />
        </button>
      ) : null}
      <label style={{ position: "relative", flex: 1, maxWidth: 420, display: "flex", alignItems: "center" }}>
        <i className="fa-solid fa-magnifying-glass" aria-hidden="true" style={{ position: "absolute", left: 12, fontSize: 11, color: "var(--text-faint)" }} />
        <input
          value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search roles, applications, contacts"
          style={{ width: "100%", background: "rgba(255,255,255,0.035)", border: "1px solid var(--hairline)", borderRadius: "var(--radius-md)", padding: "9px 12px 9px 32px", color: "var(--fg-1)", fontFamily: "var(--font-body)", fontSize: 12.5, outline: "none" }}
        />
        <span className="type-mono-micro" style={{ position: "absolute", right: 10, color: "var(--text-faint)" }}>⌘K</span>
      </label>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14 }}>
        <StatusBadge tone="ok" dot live>Live</StatusBadge>
        <button type="button" aria-label="Notifications" style={{ position: "relative", border: 0, background: "transparent", color: "var(--text-secondary)", cursor: "pointer" }}>
          <i className="fa-solid fa-bell" style={{ fontSize: 13 }} aria-hidden="true" />
          <span style={{ position: "absolute", top: -4, right: -6, minWidth: 15, height: 15, borderRadius: 999, background: "var(--gold)", color: "var(--accent-on)", fontSize: 9, fontWeight: 700, display: "grid", placeItems: "center" }}>3</span>
        </button>
        <Button tone="primary" size="sm" icon="fa-solid fa-bolt" onClick={() => onNavigate("agents")}>Run everything</Button>
        <span style={{ display: "flex", alignItems: "center", gap: 9, paddingLeft: 14, borderLeft: "1px solid var(--hairline)" }}>
          <span style={{ width: 28, height: 28, borderRadius: "var(--radius-sm)", border: "1px solid var(--gold-border)", background: "rgba(201,168,76,0.10)", color: "var(--gold)", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>PD</span>
          <span style={{ display: "grid" }}>
            <span style={{ fontSize: 11.5, fontWeight: 500 }}>Priya Deshmukh</span>
            <span className="type-meta" style={{ fontSize: 10 }}>Senior Data Analyst</span>
          </span>
        </span>
      </div>
    </header>
  );
}

Object.assign(window, { Rail, CommandBar });
