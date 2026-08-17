/* Sign in — recreated from apps/web/src/app/login/page.tsx: identifier +
   password against the shared auth client, plan context when the visitor
   arrived from /pricing, and the deliberately-minor admin entry point. */
function AuthScreen({ onView }) {
  const { Wordmark, Button, InlineNotice, OrnamentDivider } = window.__DS;
  const [mode, setMode] = React.useState("login");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

  const field = {
    background: "rgba(255,255,255,0.035)",
    border: "1px solid var(--hairline)",
    borderRadius: "var(--radius-md)",
    padding: "11px 14px",
    color: "var(--fg-1)",
    fontFamily: "var(--font-body)",
    fontSize: 13,
    outline: "none",
    width: "100%"
  };

  const submit = (e) => {
    e.preventDefault();
    if (!email || !password) { setError("Enter your email and password."); return; }
    setError(null); setBusy(true);
    setTimeout(() => { setBusy(false); setError(null); onView("done"); }, 700);
  };

  return (
    <main className="atmos-hero" style={{ minHeight: "calc(100vh - 72px)", display: "grid", placeItems: "center", padding: "64px 20px" }}>
      <div style={{ width: "100%", maxWidth: 440 }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 30 }}>
          <Wordmark size="lg" src="../../assets/aether-mark.png" />
        </div>

        <form onSubmit={submit} className="gilt-card" style={{ padding: 32, display: "grid", gap: 18 }} aria-label="Sign in">
          <div style={{ textAlign: "center" }}>
            <h1 className="type-card-title" style={{ margin: 0, fontSize: 15 }}>{mode === "login" ? "Sign in" : "Create account"}</h1>
            <div style={{ margin: "14px 0" }}><OrnamentDivider width={160} /></div>
            <p className="type-page-sub" style={{ margin: 0 }}>
              {mode === "login" ? "Access your agent dashboard." : "Start free — 10 agent runs a month, no card required."}
            </p>
          </div>

          <InlineNotice tone="gold" title="Continuing with Pro">
            You picked the Pro plan — we&apos;ll bring you back to checkout after you sign in.
          </InlineNotice>

          <label style={{ display: "grid", gap: 7 }}>
            <span className="type-section" style={{ margin: 0 }}>Email</span>
            <input type="text" name="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} style={field}
              onFocus={(e) => { e.target.style.borderColor = "var(--gold-border-strong)"; }}
              onBlur={(e) => { e.target.style.borderColor = "var(--hairline)"; }} />
          </label>

          <label style={{ display: "grid", gap: 7 }}>
            <span className="type-section" style={{ margin: 0 }}>Password</span>
            <input type="password" name="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} style={field}
              onFocus={(e) => { e.target.style.borderColor = "var(--gold-border-strong)"; }}
              onBlur={(e) => { e.target.style.borderColor = "var(--hairline)"; }} />
            <span style={{ textAlign: "right" }}>
              <a href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: 11, color: "var(--text-muted)" }}>Forgot password?</a>
            </span>
          </label>

          {error ? <InlineNotice tone="danger">{error}</InlineNotice> : null}

          <Button tone="primary" size="md" block type="submit" disabled={busy}>
            {busy ? "Signing in…" : mode === "login" ? "Sign in" : "Create account"}
          </Button>

          <p className="type-meta" style={{ textAlign: "center", margin: 0 }}>
            {mode === "login" ? (
              <>Don&apos;t have an account? <a href="#" onClick={(e) => { e.preventDefault(); setMode("signup"); }}>Create one</a></>
            ) : (
              <>Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); setMode("login"); }}>Sign in</a></>
            )}
          </p>
        </form>

        <p style={{ textAlign: "center", marginTop: 18 }}>
          <a href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-faint)" }}>Admin sign in</a>
        </p>
        <p className="type-meta" style={{ textAlign: "center", marginTop: 14 }}>
          <a href="#" onClick={(e) => { e.preventDefault(); onView("pricing"); }}>Back to pricing</a>
        </p>
      </div>
    </main>
  );
}

function SignedInScreen({ onView }) {
  const { Button, Section, OrnamentDivider } = window.__DS;
  return (
    <main className="atmos-hero" style={{ minHeight: "calc(100vh - 72px)", display: "grid", placeItems: "center", padding: "64px 20px" }}>
      <Section style={{ maxWidth: 480, padding: 40, textAlign: "center" }}>
        <h1 className="type-card-title" style={{ margin: 0, fontSize: 15 }}>Signed in</h1>
        <div style={{ margin: "16px 0" }}><OrnamentDivider width={180} /></div>
        <p className="type-body" style={{ margin: "0 auto 22px", maxWidth: "44ch" }}>
          In the product this lands on the command center. Open the app kit to see that surface.
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
          <Button tone="primary" size="sm" href="../app/index.html">Open the command center</Button>
          <Button tone="outline" size="sm" onClick={() => onView("auth")}>Back to sign in</Button>
        </div>
      </Section>
    </main>
  );
}

Object.assign(window, { AuthScreen, SignedInScreen });
