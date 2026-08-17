/* Pricing — recreated from apps/web/src/app/pricing/page.tsx: four ratified
   tiers, GST-inclusive AUD, monthly/annual switch, and the honesty note that
   plans differ by run quota rather than model quality.
   Prices and feature bullets here are FIXTURES — the real page reads
   GET /api/billing/plans. */
const PLANS = [
  { id: "free", name: "Free", month: 0, year: 0, runs: 10, purchasable: false,
    features: ["10 agent runs / month", "1 tailored resume", "Story Bank — 5 entries", "Approval required on every outbound action"] },
  { id: "starter", name: "Starter", month: 29, year: 290, runs: 50,
    features: ["50 agent runs / month", "Unlimited tailored resumes", "Cover Letter Studio", "Application tracker"] },
  { id: "pro", name: "Pro", month: 59, year: 590, runs: 200, featured: true,
    features: ["200 agent runs / month", "Interview Center", "Recruiter CRM + email agent", "Analytics and market pulse"] },
  { id: "power", name: "Power", month: 119, year: 1190, runs: 600,
    features: ["600 agent runs / month", "Offer comparison engine", "Priority discovery cadence", "Up to 3 connected mailboxes"] }
];

function PricingScreen({ onView }) {
  const { SegmentedControl, Button, Chip, StatusBadge, MetricTooltip, OrnamentDivider, InlineNotice } = window.__DS;
  const [interval, setInterval] = React.useState("month");
  const aud = (n) => "A$" + n.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const gst = (n) => aud(Math.round((n / 11) * 100) / 100);

  return (
    <main>
      <section className="atmos-hero film-grain" style={{ paddingTop: 88, paddingBottom: 56 }}>
        <div className="container-ae" style={{ textAlign: "center" }}>
          <p className="type-eyebrow" style={{ margin: "0 0 18px" }}>Autonomous career agent</p>
          <h1 className="type-display" style={{ margin: 0, maxWidth: "22ch", marginInline: "auto" }}>
            <span className="text-gilt">Simple, honest</span> pricing
          </h1>
          <div style={{ margin: "22px 0" }}><OrnamentDivider width={260} /></div>
          <p className="type-body" style={{ margin: "0 auto", maxWidth: "60ch", fontSize: 14 }}>
            All prices are in Australian dollars and GST-inclusive. Pick a plan and let Aether do the applying — cancel anytime.
          </p>
          <p className="type-meta" style={{ margin: "12px auto 0", maxWidth: "62ch" }}>
            Every plan uses the same AI models — plans differ by monthly agent-run quota and feature access, not model quality.
          </p>
          <div style={{ display: "flex", justifyContent: "center", marginTop: 30 }}>
            <SegmentedControl
              ariaLabel="Billing interval" idPrefix="interval" value={interval} onChange={setInterval}
              items={[{ value: "month", label: "Monthly" }, { value: "year", label: "Annual · save more" }]}
            />
          </div>
        </div>
      </section>

      <section className="container-ae" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 20, alignItems: "start" }}>
        {PLANS.map((p) => {
          const total = interval === "year" ? p.year : p.month;
          const isFree = !p.purchasable && p.id === "free";
          return (
            <article key={p.id} className="gilt-card" style={{ display: "flex", flexDirection: "column", padding: 26, borderColor: p.featured ? "var(--gold-border-strong)" : undefined }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <h2 className="type-card-title" style={{ margin: 0, fontSize: 14 }}>{p.name}</h2>
                {p.featured ? <StatusBadge tone="gold">Most chosen</StatusBadge> : null}
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 20 }}>
                <span className="mono" style={{ fontSize: 30, fontWeight: 500, letterSpacing: "-0.02em" }}>{isFree ? "A$0" : aud(total)}</span>
                {isFree ? null : <span className="type-meta" style={{ margin: 0 }}>/ {interval === "year" ? "year" : "month"}</span>}
              </div>
              <p className="type-meta" style={{ margin: "10px 0 0" }}>
                {isFree ? "No card required" : (
                  <MetricTooltip
                    value={"Incl. " + gst(total) + " GST"}
                    tooltip={"GST-inclusive price. Net " + aud(total - Math.round((total / 11) * 100) / 100) + " + " + gst(total) + " GST (10%, computed as round(total ÷ 11, 2))."}
                  />
                )}
              </p>
              <div style={{ marginTop: 18 }}><Chip mono tone="accent">{p.runs} runs / month</Chip></div>
              <hr className="rule-gold" style={{ margin: "20px 0" }} />
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 10, flex: 1 }}>
                {p.features.map((ftr) => (
                  <li key={ftr} style={{ display: "flex", gap: 10, fontSize: 12.5, lineHeight: 1.5, color: "var(--text-secondary)" }}>
                    <i className="fa-solid fa-check" style={{ marginTop: 3, fontSize: 10, color: "var(--gold)" }} aria-hidden="true" />
                    <span>{ftr}</span>
                  </li>
                ))}
              </ul>
              <Button tone={p.featured ? "primary" : "outline"} size="md" block style={{ marginTop: 24 }} onClick={() => onView("auth")}>
                {isFree ? "Get started free" : "Subscribe to " + p.name}
              </Button>
            </article>
          );
        })}
      </section>

      <section className="container-ae" style={{ marginTop: 34 }}>
        <InlineNotice tone="info">
          Switching plans keeps one subscription — the change is applied to your existing billing period rather than starting a second one.
        </InlineNotice>
      </section>

      <section className="container-ae" style={{ marginTop: 72, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 22 }}>
        {[
          { i: "fa-solid fa-satellite-dish", t: "Discovery that never sleeps", b: "Nine sources, scanned every six hours, scored against your resume before you see them." },
          { i: "fa-solid fa-pen-nib", t: "Evidence-backed tailoring", b: "Every rewritten line traces to a Story Bank achievement. Thin evidence is flagged, not shipped." },
          { i: "fa-solid fa-shield-halved", t: "Nothing sent without you", b: "Applications, letters and emails wait in one approval queue until you release them." }
        ].map((c) => (
          <div key={c.t} style={{ textAlign: "center" }}>
            <span style={{ display: "grid", placeItems: "center", width: 46, height: 46, marginInline: "auto", borderRadius: "var(--radius-md)", border: "1px solid var(--gold-border)", color: "var(--gold)" }}>
              <i className={c.i} style={{ fontSize: 15 }} aria-hidden="true" />
            </span>
            <h3 className="type-card-title" style={{ margin: "16px 0 0", fontSize: 12.5 }}>{c.t}</h3>
            <p className="type-body" style={{ margin: "10px auto 0", maxWidth: "34ch", fontSize: 12.5 }}>{c.b}</p>
          </div>
        ))}
      </section>

      <p className="type-meta" style={{ textAlign: "center", marginTop: 56 }}>
        Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); onView("auth"); }}>Sign in</a>
      </p>
    </main>
  );
}

Object.assign(window, { PricingScreen });
