/* Resume Studio — recreated from apps/web/src/app/dashboard/resume/page.tsx:
   version rail, the change list ("every rewritten line, and the evidence
   behind it"), keyword coverage and the evidence trace. */
function ResumeScreen() {
  const { PageHeader, SegmentedControl, Section, ListCard, Chip, Button, StatusBadge, InlineNotice, MetricTooltip, StatBlock } = window.__DS;
  const d = window.AE_DATA;
  const [version, setVersion] = React.useState("v3");
  const [tab, setTab] = React.useState("changes");

  return (
    <div>
      <div className="atmos-hero">
        <PageHeader
          title="Resume Studio"
          subtitle="Tailored against Senior Data Analyst · Telstra. Every rewritten line traces back to evidence you have already given the agent."
          action={<><Button tone="neutral" size="sm" icon="fa-solid fa-arrow-down">Download</Button><Button tone="primary" size="sm" icon="fa-solid fa-pen-nib">Retailor</Button></>}
          controls={
            <SegmentedControl
              ariaLabel="Studio view" idPrefix="studio" value={tab} onChange={setTab}
              items={[
                { value: "changes", label: "Changes", count: d.changes.length, icon: "fa-solid fa-code-compare" },
                { value: "keywords", label: "Keywords", count: d.keywords.length, icon: "fa-solid fa-key" },
                { value: "evidence", label: "Evidence", icon: "fa-solid fa-book-bookmark" }
              ]}
            />
          }
          footnote="A highlighted preview only — the file you download is unmarked."
        />
      </div>

      <div className="grid-3pane">
        <div style={{ display: "grid", gap: 10 }}>
          <p className="type-section" style={{ margin: "0 0 2px" }}>Versions</p>
          {d.resumeVersions.map((v) => (
            <ListCard key={v.id} selected={v.id === version} onClick={() => setVersion(v.id)}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                <div style={{ minWidth: 0 }}>
                  <p className="type-label" style={{ margin: 0, fontSize: 12.5 }}>{v.name}</p>
                  <p className="type-mono-micro" style={{ margin: "5px 0 0", color: "var(--text-faint)" }}>{v.when}</p>
                </div>
                <Chip mono tone={v.ats >= 85 ? "accent" : "neutral"}>ATS {v.ats}</Chip>
              </div>
              {v.master ? <div style={{ marginTop: 9 }}><StatusBadge tone="gold">Master</StatusBadge></div> : null}
              {v.current ? <div style={{ marginTop: 9 }}><StatusBadge tone="ok" dot>Current draft</StatusBadge></div> : null}
            </ListCard>
          ))}
          <Button tone="neutral" size="sm" block icon="fa-solid fa-upload" style={{ marginTop: 4 }}>Upload a resume</Button>
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {tab === "changes" ? (
            <Section
              accent
              eyebrow="Diff"
              title="Every rewritten line, and the evidence behind it"
              action={<Chip mono tone="accent">6 rewrites</Chip>}
              footnote="A rewrite with thin evidence is flagged, never silently shipped."
              style={{ padding: 24 }}
              bodyStyle={{ display: "grid", gap: 14 }}
            >
              {d.changes.map((c, i) => (
                <div key={i} className="elev-1" style={{ borderRadius: "var(--radius-xl)", padding: 16 }}>
                  <p className="type-mono-micro" style={{ margin: 0, color: "var(--state-danger)", textDecoration: "line-through", opacity: 0.75 }}>{c.was}</p>
                  <p style={{ margin: "10px 0 0", fontSize: 13, lineHeight: 1.6, color: "var(--text-primary)" }}>{c.now}</p>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 8, marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--gold-muted)" }}>
                    <i className={c.tone === "ok" ? "fa-solid fa-link" : "fa-solid fa-triangle-exclamation"} style={{ marginTop: 3, fontSize: 10, color: c.tone === "ok" ? "var(--gold)" : "var(--state-warn)" }} aria-hidden="true" />
                    <p className="type-meta" style={{ margin: 0 }}>{c.why}</p>
                  </div>
                </div>
              ))}
            </Section>
          ) : null}

          {tab === "keywords" ? (
            <Section
              eyebrow="ATS"
              title="Keyword coverage"
              action={<Chip mono tone="accent">4 of 6 covered</Chip>}
              footnote="Counted against the posting's own must-have list — not a generic keyword bank."
              style={{ padding: 24 }}
            >
              <div style={{ display: "grid", gap: 9 }}>
                {d.keywords.map((k) => (
                  <div key={k.k} style={{ display: "grid", gridTemplateColumns: "1fr 64px 96px", alignItems: "center", gap: 12 }}>
                    <span style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>{k.k}</span>
                    <span className="type-mono-micro" style={{ color: k.ok ? "var(--text-primary)" : "var(--state-neutral)" }}>{k.n}×</span>
                    {k.ok ? <StatusBadge tone="ok">Covered</StatusBadge> : <StatusBadge tone="neutral">Missing</StatusBadge>}
                  </div>
                ))}
              </div>
            </Section>
          ) : null}

          {tab === "evidence" ? (
            <Section
              eyebrow="Trace"
              title="Evidence behind this draft"
              footnote="Every claim in the tailored resume resolves to one of these entries."
              style={{ padding: 24 }}
              bodyStyle={{ display: "grid", gap: 10 }}
            >
              {[
                { t: "Growth reporting rebuild", m: "40 min → 90 s · 120 weekly users", used: 3 },
                { t: "Experimentation program", m: "34 tests · 9 shipped · 6.2% activation lift", used: 2 },
                { t: "Data contract rollout", m: "61 dbt models · 99% freshness SLA", used: 1 }
              ].map((s) => (
                <div key={s.t} className="elev-1" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, borderRadius: "var(--radius-xl)", padding: "13px 16px" }}>
                  <div style={{ minWidth: 0 }}>
                    <p className="type-label" style={{ margin: 0, fontSize: 12.5 }}>{s.t}</p>
                    <p className="type-mono-micro" style={{ margin: "5px 0 0", color: "var(--text-faint)" }}>{s.m}</p>
                  </div>
                  <Chip mono tone="accent">{s.used} lines</Chip>
                </div>
              ))}
            </Section>
          ) : null}
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          <StatBlock label="ATS score" value={<MetricTooltip value="91" tooltip="Keyword coverage, section order and format checks run against the posting — not a guarantee any employer's parser agrees." />} note="up 19 from the master resume" delta={19} />
          <Section eyebrow="Voice" title="Voice DNA" style={{ padding: 20 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
              <Chip>plain</Chip><Chip>evidence-first</Chip><Chip>no superlatives</Chip><Chip tone="accent">measured</Chip>
            </div>
            <p className="type-meta" style={{ margin: "12px 0 0" }}>Learned from 14 Story Bank entries and 3 past resumes.</p>
          </Section>
          <InlineNotice tone="warn" title="One line is thin">
            The data-quality bullet cites a figure from your 2025 review rather than a Story Bank entry. Add the evidence or drop the number.
          </InlineNotice>
          <Button tone="ok" size="md" block icon="fa-solid fa-paper-plane">Approve &amp; queue application</Button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ResumeScreen });
