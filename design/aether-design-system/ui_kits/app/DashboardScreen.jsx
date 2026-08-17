/* Dashboard hub — recreated from apps/web/src/app/dashboard/page.tsx:
   pulse band, agent activity feed, today's opportunities, funnel,
   needs-approval queue, live ticker, story bank and recruiter CRM. */
const FEED_FILTERS = ["All", "Discovered", "Tailored", "Submitted", "Waiting"];

function AgentFeed() {
  const { Section, Chip, StatusBadge, Button } = window.__DS;
  const [filter, setFilter] = React.useState("All");
  const [approved, setApproved] = React.useState([]);
  const rows = window.AE_DATA.runs.filter((r) => filter === "All" || r.stage === filter);
  return (
    <Section
      eyebrow="Pipeline"
      title="Agent activity"
      action={<Button tone="quiet" size="xs" iconAfter="fa-solid fa-arrow-right">View all</Button>}
      style={{ padding: 22 }}
    >
      <div role="group" aria-label="Filter agent activity" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
        {FEED_FILTERS.map((f) => (
          <Chip key={f} selected={filter === f} onClick={() => setFilter(f)}>{f}</Chip>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="type-meta" style={{ margin: 0 }}>No “{filter}” activity in the latest runs.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 14 }}>
          {rows.map((r, i) => (
            <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 13 }}>
              <span style={{ flexShrink: 0, width: 32, height: 32, display: "grid", placeItems: "center", borderRadius: "var(--radius-md)", border: "1px solid var(--gold-muted)", background: "rgba(201,168,76,0.07)", color: "var(--gold)" }}>
                <i className={r.icon} style={{ fontSize: 11 }} aria-hidden="true" />
              </span>
              <div style={{ minWidth: 0, flex: 1 }}>
                <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: "var(--text-secondary)" }}>
                  <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>{r.agent}</span>{" "}{r.text}{" "}
                  <span style={{ color: "var(--text-primary)" }}>{r.highlight}</span>
                </p>
                <p className="type-mono-micro" style={{ margin: "5px 0 0", color: "var(--text-faint)" }}>{r.meta}</p>
                {r.approve && !approved.includes(i) ? (
                  <Button tone="ok" size="xs" style={{ marginTop: 9 }} onClick={() => setApproved(approved.concat(i))}>Approve</Button>
                ) : null}
                {r.approve && approved.includes(i) ? (
                  <p className="type-mono-micro" style={{ margin: "8px 0 0", color: "var(--state-ok)" }}>approved · queued for send</p>
                ) : null}
              </div>
              <StatusBadge tone={r.tone} dot={r.live} live={r.live}>{r.stage}</StatusBadge>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Opportunities({ onNavigate }) {
  const { Section, Button, Chip } = window.__DS;
  return (
    <Section
      eyebrow="Discovery"
      title="Today's opportunities"
      action={<Button tone="quiet" size="xs" onClick={() => onNavigate("jobs")}>Browse all jobs</Button>}
      style={{ padding: 22 }}
      bodyStyle={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))", gap: 14 }}
    >
      {window.AE_DATA.opportunities.map((j, i) => (
        <article key={j.org} className="elev-2" style={{ display: "flex", flexDirection: "column", borderRadius: "var(--radius-xl)", padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <span style={{ width: 34, height: 34, display: "grid", placeItems: "center", borderRadius: "var(--radius-sm)", background: "rgba(255,255,255,0.07)", fontSize: 11, fontWeight: 700, letterSpacing: "0.04em" }}>
              {j.org.split(" ").map((w) => w[0]).slice(0, 2).join("")}
            </span>
            <Chip mono tone={j.fit >= 85 ? "accent" : "neutral"}>{j.fit}% fit</Chip>
          </div>
          <h4 className="type-label" style={{ margin: 0, fontSize: 13.5, lineHeight: 1.35 }}>{j.role}</h4>
          <p className="type-meta" style={{ margin: "4px 0 0" }}>{j.org} · {j.where}</p>
          <p className="type-mono-micro" style={{ margin: "9px 0 0", color: "var(--text-faint)" }}>{j.pay}</p>
          <Button tone={i === 0 ? "primary" : "neutral"} size="sm" block style={{ marginTop: 14 }} onClick={() => onNavigate(i === 0 ? "resume" : "jobs")}>
            {i === 0 ? "Tailor & apply" : "Review match"}
          </Button>
        </article>
      ))}
    </Section>
  );
}

function FunnelPanel() {
  const { Section } = window.__DS;
  const steps = window.AE_DATA.funnel;
  const max = steps[0].n;
  return (
    <Section
      eyebrow="Analytics"
      title="Application funnel"
      footnote="All time — every stage counted since your first discovery run."
      style={{ padding: 22 }}
    >
      <div style={{ display: "grid", gap: 9 }}>
        {steps.map((s, i) => {
          const share = i === 0 ? 100 : Math.round((s.n / steps[i - 1].n) * 100);
          return (
            <div key={s.stage} style={{ display: "grid", gridTemplateColumns: "110px 1fr 78px", alignItems: "center", gap: 12 }}>
              <span className="type-meta" style={{ margin: 0 }}>{s.stage}</span>
              <span style={{ height: 8, borderRadius: 2, background: "rgba(255,255,255,0.05)", overflow: "hidden" }}>
                <span style={{ display: "block", height: "100%", width: Math.max(1.5, (s.n / max) * 100) + "%", background: "linear-gradient(90deg,var(--gold-dark),var(--gold-light))", opacity: 0.35 + 0.65 * (s.n / max) }} />
              </span>
              <span className="type-mono-micro" style={{ textAlign: "right", color: "var(--text-secondary)" }}>
                {s.n} <span style={{ color: "var(--text-faint)" }}>· {share}%</span>
              </span>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function ApprovalQueue() {
  const { Section, Button, StatusBadge, InlineNotice } = window.__DS;
  const [queue, setQueue] = React.useState(window.AE_DATA.approvals);
  const [notice, setNotice] = React.useState(null);
  const resolve = (i, action) => {
    setQueue(queue.filter((_, k) => k !== i));
    setNotice(action === "approve" ? "Approved — the action is queued for send." : "Rejected — nothing was sent.");
  };
  return (
    <Section
      accent
      eyebrow="Human in the loop"
      title="Needs approval"
      action={<StatusBadge tone="warn">{queue.length} waiting</StatusBadge>}
      style={{ padding: 22 }}
    >
      {notice ? <div style={{ marginBottom: 12 }}><InlineNotice tone="ok" onDismiss={() => setNotice(null)}>{notice}</InlineNotice></div> : null}
      {queue.length === 0 ? (
        <p className="type-body" style={{ margin: 0 }}>Queue clear — nothing is waiting on you right now.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 12 }}>
          {queue.map((a, i) => (
            <li key={a.title + i} className="elev-1" style={{ borderRadius: "var(--radius-xl)", padding: 15 }}>
              <p className="type-label" style={{ margin: 0 }}>{a.title}</p>
              <p className="type-meta" style={{ margin: "4px 0 0" }}>{a.sub}</p>
              <p className="type-mono-micro" style={{ margin: "9px 0 0", color: "var(--text-faint)" }}>{a.when}</p>
              <div style={{ display: "flex", gap: 8, marginTop: 13 }}>
                <Button tone="ok" size="sm" block onClick={() => resolve(i, "approve")}>Approve</Button>
                <Button tone="danger" size="sm" block onClick={() => resolve(i, "reject")}>Reject</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Ticker() {
  const { Section, StatusBadge } = window.__DS;
  return (
    <Section
      className="band-recessed"
      eyebrow="Live"
      title="Activity stream"
      action={<StatusBadge tone="ok" dot live>Streaming</StatusBadge>}
      style={{ padding: 22 }}
    >
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
        {window.AE_DATA.ticker.map((t) => (
          <li key={t.t} className="type-mono-micro" style={{ display: "flex", gap: 12, color: "var(--text-secondary)" }}>
            <span style={{ color: "var(--gold)", opacity: 0.7 }}>{t.t}</span>
            <span style={{ minWidth: 0 }}>{t.m}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function StoryBankWidget({ onNavigate }) {
  const { Section, Button, Chip } = window.__DS;
  const stories = [
    { t: "Growth reporting rebuild", n: 3 },
    { t: "Experimentation program", n: 2 },
    { t: "Data contract rollout", n: 2 }
  ];
  return (
    <Section
      eyebrow="Evidence"
      title="Story bank"
      action={<Button tone="quiet" size="xs" iconAfter="fa-solid fa-arrow-right" onClick={() => onNavigate("stories")}>Open</Button>}
      style={{ padding: 22 }}
    >
      <p className="type-body" style={{ margin: "0 0 14px" }}>
        <span className="mono" style={{ color: "var(--text-primary)", fontWeight: 600 }}>14</span> STAR achievements ready to deploy
      </p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
        {stories.map((s) => (
          <li key={s.t} className="elev-1" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, borderRadius: "var(--radius-lg)", padding: "9px 12px" }}>
            <span style={{ fontSize: 12, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.t}</span>
            <Chip mono tone="accent">{s.n} metrics</Chip>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function CrmWidget({ onNavigate }) {
  const { Section, Button } = window.__DS;
  const rows = [
    { icon: "fa-solid fa-comments", n: 5, label: "active recruiter conversations", tone: "var(--state-ok)" },
    { icon: "fa-solid fa-clock", n: 2, label: "follow-ups due today", tone: "var(--state-warn)" },
    { icon: "fa-solid fa-user-plus", n: 1, label: "warm intro pending", tone: "var(--sapphire-light)" }
  ];
  return (
    <Section
      eyebrow="Network"
      title="Recruiter CRM"
      action={<Button tone="quiet" size="xs" iconAfter="fa-solid fa-arrow-right" onClick={() => onNavigate("networking")}>Open</Button>}
      style={{ padding: 22 }}
    >
      <div style={{ display: "grid", gap: 11 }}>
        {rows.map((r) => (
          <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ width: 30, height: 30, display: "grid", placeItems: "center", borderRadius: "var(--radius-sm)", background: "rgba(255,255,255,0.05)", color: r.tone }}>
              <i className={r.icon} style={{ fontSize: 11 }} aria-hidden="true" />
            </span>
            <p className="type-body" style={{ margin: 0, fontSize: 12.5 }}>
              <span className="mono" style={{ color: "var(--text-primary)", fontWeight: 600 }}>{r.n}</span> {r.label}
            </p>
          </div>
        ))}
      </div>
    </Section>
  );
}

function DashboardScreen({ onNavigate }) {
  const { StatBlock, MetricTooltip } = window.__DS;
  return (
    <div style={{ display: "grid", gap: 26 }}>
      <section className="atmos-hero">
        <div style={{ marginBottom: 20 }}>
          <h1 className="type-page" style={{ margin: 0 }}>
            <span className="text-gilt">Your search</span>, right now
          </h1>
          <p className="type-page-sub" style={{ margin: "10px 0 0" }}>Every figure below is fetched live from your workspace.</p>
        </div>
        <div className="grid-stats">
          {window.AE_DATA.stats.map((s) => (
            <StatBlock key={s.label} label={s.label} unit={s.unit} delta={s.delta ?? null} note={s.note}>
              <MetricTooltip value={s.value} tooltip={s.tip} />
            </StatBlock>
          ))}
        </div>
      </section>

      <div className="grid-7-5">
        <div style={{ display: "grid", gap: 22, minWidth: 0 }}>
          <AgentFeed />
          <Opportunities onNavigate={onNavigate} />
          <FunnelPanel />
        </div>
        <div style={{ display: "grid", gap: 22, minWidth: 0 }}>
          <ApprovalQueue />
          <Ticker />
          <StoryBankWidget onNavigate={onNavigate} />
          <CrmWidget onNavigate={onNavigate} />
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DashboardScreen });
