/* Public surface — nav + footer, recreated from apps/web/src/app/pricing/page.tsx
   and components/PublicFooter.tsx. */
function PublicNav({ view, onView }) {
  const { Wordmark, Button } = window.__DS;
  const links = [["pricing", "Pricing"], ["auth", "Sign in"]];
  return (
    <header className="chrome-blur" style={{ position: "sticky", top: 0, zIndex: 30, borderBottom: "1px solid var(--hairline)" }}>
      <div className="container-ae" style={{ display: "flex", alignItems: "center", gap: 20, minHeight: 72 }}>
        <a href="#" onClick={(e) => { e.preventDefault(); onView("pricing"); }} style={{ textDecoration: "none" }}>
          <Wordmark size="sm" src="../../assets/aether-mark.png" />
        </a>
        <nav style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 24 }}>
          {links.map(([k, label]) => (
            <a key={k} href="#" onClick={(e) => { e.preventDefault(); onView(k); }}
              style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", textDecoration: "none", color: view === k ? "var(--gold)" : "var(--text-secondary)" }}>
              {label}
            </a>
          ))}
          <Button tone="primary" size="sm" onClick={() => onView("auth")}>Get started</Button>
        </nav>
      </div>
    </header>
  );
}

function PublicFooter() {
  const { OrnamentDivider } = window.__DS;
  return (
    <footer style={{ marginTop: 80, paddingBottom: 48 }}>
      <div className="container-ae">
        <OrnamentDivider width="full" />
        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px 24px", justifyContent: "center", marginTop: 26 }}>
          {["Privacy policy", "Terms", "Contact support", "Admin sign in"].map((l) => (
            <a key={l} href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)", textDecoration: "none" }}>{l}</a>
          ))}
        </div>
        <p className="type-meta" style={{ textAlign: "center", margin: "18px 0 0" }}>© 2026 Aether · Prices in Australian dollars, GST inclusive</p>
      </div>
    </footer>
  );
}

Object.assign(window, { PublicNav, PublicFooter });
