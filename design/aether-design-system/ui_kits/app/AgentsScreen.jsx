/* Agents console — recreated from apps/web/src/app/dashboard/agents/page.tsx:
   the conductor band, the agent config grid and the run policy panel. */
function AgentsScreen() {
  const { PageHeader, SegmentedControl, Section, Chip, Button, StatusBadge, InlineNotice, StatBlock, MetricTooltip } = window.__DS;
  const d = window.AE_DATA;
  const [tab, setTab] = React.useState("fleet");
  const [paused, setPaused] = React.useState(false);
  const [running, setRunning] = React.useState(false);

  return (
    <div>
      <div className="atmos-hero">
        <PageHeader
          title="Agent Orchestration"
          subtitle="Six agents, one pipeline: discover, score, tailor, draft, submit, follow up. Nothing leaves the system without your approval."
          action={
            <>
              <Button tone="neutral" size="sm" icon={paused ? "fa-solid fa-play" : "fa-solid fa-pause"} onClick={() => setPaused(!paused)}>
                {paused ? "Resume all" : "Pause all"}
              </Button>
              <Button tone="primary" size="sm" icon="fa-solid fa-bolt" onClick={() => setRunning(true)}>Run everything</Button>
            </>
          }
          controls={
            <SegmentedControl
              ariaLabel="Agents view" idPrefix="agents" value={tab} onChange={setTab}
              items={[
                { value: "fleet", label: "Fleet", count: d.agents.length, icon: "fa-solid fa-robot" },
                { value: "policy", label: "Run policy", icon: "fa-solid fa-shield-halved" },
                { value: "providers", label: "Providers", count: 2, icon: "fa-solid fa-plug" }
              ]}
            />
          }
        />
      </div>

      {paused ? (
        <div style={{ marginBottom: 18 }}>
          <InlineNotice tone="warn" title="Fleet paused">No new runs are being scheduled. Runs already in flight will finish.</InlineNotice>
        </div>
      ) : null}
      {running ? (
        <div style={{ marginBottom: 18 }}>
          <InlineNotice tone="ok" onDismiss={() => setRunning(false)}>Pipeline queued — Scout starts first; each stage waits for the one before it.</InlineNotice>
        </div>
      ) : null}

      <div className="grid-stats" style={{ marginBottom: 22 }}>
        <StatBlock label="Runs this period" value={<MetricTooltip value="68" tooltip="Agent runs counted against your plan quota since the period opened on 1 August." />} unit="/200" note="Pro plan · resets 1 Sep" />
        <StatBlock label="Median run time" value="41" unit="s" note="across 214 Scout runs" />
        <StatBlock label="Spend this period" value="12.40" unit="AUD" note="GST inclusive" />
        <StatBlock label="Stalled runs" value="1" note="Scribe · 2 h without progress" delta={1} />
      </div>

      {tab === "fleet" ? (
        <div className="grid-cards">
          {d.agents.map((a) => (
            <article key={a.name} className="elev-1" style={{ borderRadius: "var(--radius-2xl)", padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
                  <span style={{ width: 34, height: 34, display: "grid", placeItems: "center", borderRadius: "var(--radius-md)", border: "1px solid var(--gold-muted)", background: "rgba(201,168,76,0.07)", color: "var(--gold)" }}>
                    <i className={a.icon} style={{ fontSize: 12 }} aria-hidden="true" />
                  </span>
                  <span style={{ minWidth: 0 }}>
                              <p className="type-card-title" style={{ margin: 0, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</p>
                    <p className="type-meta" style={{ margin: "4px 0 0" }}>{a.role}</p>
                  </span>
                </span>
                <StatusBadge tone={a.status} dot={a.status === "ok"} live={a.status === "ok" && !paused}>{a.statusLabel}</StatusBadge>
              </div>
              <p className="type-body" style={{ margin: 0, fontSize: 12.5 }}>{a.note}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                <Chip mono icon="fa-solid fa-microchip">{a.model}</Chip>
                <Chip mono icon="fa-solid fa-clock-rotate-left">{a.last}</Chip>
                <Chip mono>{a.runs} runs</Chip>
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: "auto", paddingTop: 4 }}>
                <Button tone="neutral" size="xs" block icon="fa-solid fa-sliders">Configure</Button>
                <Button tone="outline" size="xs" block icon="fa-solid fa-play">Test run</Button>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {tab === "policy" ? (
        <div className="grid-7-5">
          <Section
            accent
            eyebrow="Human in the loop"
            title="What the fleet may do unattended"
            footnote="Every gate below is enforced server-side; turning one off in the UI cannot bypass it."
            style={{ padding: 24 }}
            bodyStyle={{ display: "grid", gap: 12 }}
          >
            {[
              { t: "Discover and score roles", v: "Automatic", tone: "ok" },
              { t: "Tailor a resume", v: "Automatic", tone: "ok" },
              { t: "Draft a cover letter", v: "Automatic", tone: "ok" },
              { t: "Send a cover letter or email", v: "Needs approval", tone: "warn" },
              { t: "Submit an application", v: "Needs approval", tone: "warn" },
              { t: "Respond to an offer", v: "Needs approval", tone: "warn" }
            ].map((r) => (
              <div key={r.t} className="elev-1" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, borderRadius: "var(--radius-xl)", padding: "13px 16px" }}>
                <p className="type-label" style={{ margin: 0, fontSize: 12.5 }}>{r.t}</p>
                <StatusBadge tone={r.tone}>{r.v}</StatusBadge>
              </div>
            ))}
          </Section>
          <div style={{ display: "grid", gap: 16 }}>
            <Section eyebrow="Quality floor" title="Below-floor artifacts" style={{ padding: 20 }}>
              <p className="type-body" style={{ margin: 0, fontSize: 12.5 }}>An artifact scoring under ATS 70 is held back and marked. You can approve it anyway, once, with an acknowledgement.</p>
              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <Chip mono tone="warn">floor · ATS 70</Chip>
                <Chip mono>2 held this period</Chip>
              </div>
            </Section>
            <Section eyebrow="Cadence" title="Schedule" style={{ padding: 20 }}>
              <div style={{ display: "grid", gap: 9 }}>
                {[["Discovery", "every 6 h"], ["Scoring", "on new rows"], ["Tailoring", "on request"], ["Follow-ups", "daily 09:00 AEST"]].map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <span className="type-meta" style={{ margin: 0 }}>{k}</span>
                    <span className="type-mono-micro" style={{ color: "var(--text-secondary)" }}>{v}</span>
                  </div>
                ))}
              </div>
            </Section>
          </div>
        </div>
      ) : null}

      {tab === "providers" ? (
        <div className="grid-cards">
          <Section eyebrow="Model provider" title="Anthropic" action={<StatusBadge tone="ok" dot>Connected</StatusBadge>} style={{ padding: 22 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
              <Chip mono>claude-opus-4-1</Chip><Chip mono>claude-sonnet-4-5</Chip><Chip mono>claude-haiku-4-5</Chip>
            </div>
            <p className="type-meta" style={{ margin: "12px 0 0" }}>Every plan resolves the same model per task type — plans differ by run quota, not model quality.</p>
          </Section>
          <Section eyebrow="Mailbox" title="Gmail" action={<StatusBadge tone="neutral">Not connected</StatusBadge>} style={{ padding: 22 }}>
            <p className="type-body" style={{ margin: 0, fontSize: 12.5 }}>Connect a mailbox to let Envoy read job-alert emails and send approved follow-ups.</p>
            <Button tone="outline" size="sm" style={{ marginTop: 14 }} icon="fa-solid fa-link">Connect mailbox</Button>
          </Section>
        </div>
      ) : null}
    </div>
  );
}

Object.assign(window, { AgentsScreen });
