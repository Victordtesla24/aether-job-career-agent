/* Job Discovery — two-pane browser recreated from
   apps/web/src/app/dashboard/jobs/page.tsx (list pane + detail pane). */
function JobsScreen() {
  const { PageHeader, SegmentedControl, Section, ListCard, Chip, Button, StatusBadge, InlineNotice, MetricTooltip } = window.__DS;
  const jobs = window.AE_DATA.jobs;
  const [market, setMarket] = React.useState("all");
  const [activeId, setActiveId] = React.useState(jobs[0].id);
  const [saved, setSaved] = React.useState(jobs.filter((j) => j.saved).map((j) => j.id));
  const shown = market === "saved" ? jobs.filter((j) => saved.includes(j.id)) : jobs;
  const job = jobs.find((j) => j.id === activeId) || jobs[0];
  const toggleSave = (id) => setSaved(saved.includes(id) ? saved.filter((s) => s !== id) : saved.concat(id));

  return (
    <div>
      <div className="atmos-hero">
        <PageHeader
          title="Job Discovery"
          subtitle="Every role below was discovered by your agents and scored against your resume."
          action={<><Button tone="outline" size="sm" icon="fa-solid fa-sliders">Filters</Button><Button tone="primary" size="sm" icon="fa-solid fa-satellite-dish">Run scout</Button></>}
          controls={
            <SegmentedControl
              ariaLabel="Market" idPrefix="market" value={market} onChange={setMarket}
              items={[
                { value: "all", label: "All roles", count: jobs.length, icon: "fa-solid fa-layer-group" },
                { value: "au", label: "Australia", count: 96 },
                { value: "saved", label: "Saved", count: saved.length, icon: "fa-solid fa-bookmark" }
              ]}
            />
          }
          footnote="Counts are what the discovery stream has actually observed this session — never a cached estimate."
        />
      </div>

      <div className="grid-2pane">
        <div style={{ display: "grid", gap: 10 }}>
          {shown.map((j) => (
            <ListCard key={j.id} selected={j.id === activeId} onClick={() => setActiveId(j.id)}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <p className="type-label" style={{ margin: 0, fontSize: 13 }}>{j.role}</p>
                  <p className="type-meta" style={{ margin: "4px 0 0" }}>{j.org} · {j.where}</p>
                </div>
                {j.fit === null
                  ? <StatusBadge tone="neutral">Not scored</StatusBadge>
                  : <Chip mono tone={j.fit >= 85 ? "accent" : "neutral"}>{j.fit}%</Chip>}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 11 }}>
                <Chip mono>{j.pay}</Chip>
                <Chip icon="fa-solid fa-rss">{j.source}</Chip>
                <Chip mono icon="fa-solid fa-clock">{j.age}</Chip>
              </div>
            </ListCard>
          ))}
          {shown.length === 0 ? <InlineNotice tone="info">Nothing saved yet — star a role to keep it here.</InlineNotice> : null}
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          <Section
            accent
            eyebrow={job.source + " · " + job.age + " ago"}
            title={job.role}
            subtitle={job.org + " · " + job.where}
            action={
              <>
                <Button tone="neutral" size="sm" icon={saved.includes(job.id) ? "fa-solid fa-bookmark" : "fa-regular fa-bookmark"} onClick={() => toggleSave(job.id)}>
                  {saved.includes(job.id) ? "Saved" : "Save"}
                </Button>
                <Button tone="primary" size="sm" icon="fa-solid fa-pen-nib">Tailor &amp; apply</Button>
              </>
            }
            footnote="Fit and ATS are scored at discovery time and rescored whenever your master resume changes."
            style={{ padding: 24 }}
          >
            <div className="grid-mini" style={{ marginBottom: 20 }}>
              <div className="elev-2" style={{ borderRadius: "var(--radius-xl)", padding: 15 }}>
                <p className="type-section" style={{ margin: 0 }}>Fit score</p>
                <p className="mono" style={{ margin: "10px 0 0", fontSize: 26, lineHeight: 1, color: job.fit === null ? "var(--state-neutral)" : "var(--gold)" }}>
                  {job.fit === null ? "—" : <MetricTooltip value={job.fit + "%"} tooltip="How closely the posting's must-have skills match evidence in your resume and Story Bank." />}
                </p>
                <p className="type-meta" style={{ margin: "8px 0 0" }}>{job.fit === null ? "not scored yet" : "vs your master resume"}</p>
              </div>
              <div className="elev-2" style={{ borderRadius: "var(--radius-xl)", padding: 15 }}>
                <p className="type-section" style={{ margin: 0 }}>ATS score</p>
                <p className="mono" style={{ margin: "10px 0 0", fontSize: 26, lineHeight: 1, color: job.ats === null ? "var(--state-neutral)" : "var(--text-primary)" }}>{job.ats === null ? "—" : job.ats}</p>
                <p className="type-meta" style={{ margin: "8px 0 0" }}>{job.ats === null ? "no tailored version" : "keyword + format pass"}</p>
              </div>
              <div className="elev-2" style={{ borderRadius: "var(--radius-xl)", padding: 15 }}>
                <p className="type-section" style={{ margin: 0 }}>Salary band</p>
                <p className="mono" style={{ margin: "10px 0 0", fontSize: 15, lineHeight: 1.4 }}>{job.pay}</p>
                <p className="type-meta" style={{ margin: "8px 0 0" }}>as advertised</p>
              </div>
            </div>

            <p className="type-eyebrow" style={{ margin: "0 0 8px" }}>Why the agent scored it this way</p>
            {job.why.length === 0 ? (
              <InlineNotice tone="degraded">This role has not been scored, so there is no reasoning to show.</InlineNotice>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
                {job.why.map((w) => (
                  <li key={w} style={{ display: "flex", gap: 10, fontSize: 12.5, lineHeight: 1.55, color: "var(--text-secondary)" }}>
                    <i className="fa-solid fa-angle-right" style={{ marginTop: 4, fontSize: 9, color: "var(--gold)" }} aria-hidden="true" />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            )}

            <hr className="rule-gold" style={{ margin: "20px 0" }} />
            <p className="type-eyebrow" style={{ margin: "0 0 8px" }}>The posting</p>
            <p className="type-body" style={{ margin: 0, maxWidth: "72ch" }}>{job.blurb}</p>
          </Section>

          <Section eyebrow="Provenance" title="Where this came from" style={{ padding: 22 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <Chip icon="fa-solid fa-rss">{job.source}</Chip>
              <Chip mono icon="fa-solid fa-fingerprint">job_{job.id}f2c41</Chip>
              <Chip mono icon="fa-solid fa-clock">observed {job.age} ago</Chip>
              <Chip icon="fa-solid fa-arrow-up-right-from-square">original posting</Chip>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { JobsScreen });
