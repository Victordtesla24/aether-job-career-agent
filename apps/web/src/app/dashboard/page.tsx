"use client";

/**
 * Dashboard home — live stat cards (GET /analytics/funnel), today's top
 * opportunities (GET /jobs), the Application Funnel widget (DEF-014) and the
 * Recruiter CRM summary widget (DEF-015, GET /networking/summary).
 * Funnel numbers are data-driven per REQ-TM-09 — never hardcoded.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import DashboardStats from "../../components/dashboard/DashboardStats";
import { fetchAgentRuns, type AgentRun } from "../../lib/api/agents";
import { fetchFunnel, type Funnel } from "../../lib/api/analytics";
import { fetchApprovals, type Approval } from "../../lib/api/approvals";
import { apiRequest } from "../../lib/api/client";
import type { Job } from "../../lib/api/jobs";
import { fetchNetworkingSummary, type NetworkingSummary } from "../../lib/api/workspaces";

const FUNNEL_STAGES: Array<{ key: keyof Funnel & string; label: string; color: string }> = [
  { key: "jobs_found", label: "Jobs Found", color: "bg-aether-violet" },
  { key: "applied", label: "Applied", color: "bg-aether-violet/80" },
  { key: "screened", label: "Screened", color: "bg-aether-coral" },
  { key: "interviewed", label: "Interviewed", color: "bg-aether-amber" },
  { key: "offers", label: "Offers", color: "bg-aether-green" },
];

/** Feed badge per run (wireframe feed: Discovered / Tailored / Submitted / Waiting). */
function runBadge(run: AgentRun): { label: string; cls: string } {
  if (run.status === "queued" || run.status === "running") {
    return { label: "Waiting", cls: "border-aether-amber/30 text-aether-amber" };
  }
  if (run.status === "failed") {
    return { label: "Failed", cls: "border-red-500/30 text-red-300" };
  }
  const byAgent: Record<string, string> = {
    scout: "Discovered",
    tailor: "Tailored",
    submission: "Submitted",
    coverLetter: "Drafted",
  };
  return {
    label: byAgent[run.agentName] ?? "Completed",
    cls: "border-aether-green/30 text-aether-green",
  };
}

const FEED_FILTERS = ["All", "Discovered", "Tailored", "Submitted", "Waiting"] as const;

function initials(company: string) {
  return company
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function DashboardPage() {
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [crm, setCrm] = useState<NetworkingSummary["crmSummary"] | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [pending, setPending] = useState<Approval[]>([]);
  const [feedFilter, setFeedFilter] = useState<(typeof FEED_FILTERS)[number]>("All");

  useEffect(() => {
    fetchFunnel("all").then(setFunnel).catch(() => setFunnel(null));
    fetchAgentRuns().then(setRuns).catch(() => setRuns([]));
    fetchApprovals("pending").then(setPending).catch(() => setPending([]));
    apiRequest<Job[]>("/jobs?sort=fitScore")
      .then((list) => setJobs(list.slice(0, 3)))
      .catch(() => setJobs([]));
    fetchNetworkingSummary()
      .then((n) => setCrm(n.crmSummary))
      .catch(() => setCrm(null));
  }, []);

  const maxStage = funnel ? Math.max(funnel.jobs_found, 1) : 1;

  return (
    <div className="grid gap-7 xl:grid-cols-3">
      {/* Left 2/3 */}
      <div className="flex flex-col gap-7 xl:col-span-2">
        <DashboardStats />

        <section className="glass rounded-2xl border border-white/10 p-6" data-testid="agent-feed">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="w-2 h-2 rounded-full bg-aether-green live-dot" />
              <h2 className="text-[15px] font-semibold">Agent Activity</h2>
              <span className="text-[11px] text-aether-muted-dim mono">live</span>
            </div>
            <Link href="/dashboard/agents" className="text-xs text-aether-coral transition hover:text-white">
              View all
            </Link>
          </div>
          <div className="mb-3 flex flex-wrap gap-1.5" role="tablist" aria-label="Feed filters">
            {FEED_FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                role="tab"
                aria-selected={feedFilter === f}
                onClick={() => setFeedFilter(f)}
                className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                  feedFilter === f
                    ? "border-aether-coral/50 bg-aether-coral/15 font-semibold text-aether-coral"
                    : "border-white/10 text-aether-muted hover:text-white"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          {runs.length === 0 ? (
            <p className="text-sm text-aether-muted">
              No agent activity yet — head to the{" "}
              <Link href="/dashboard/agents" className="text-aether-coral underline underline-offset-2">
                Agents workspace
              </Link>{" "}
              to launch the discovery → tailoring pipeline. Anything that leaves the system waits
              for your approval first.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {runs
                .filter((r) => feedFilter === "All" || runBadge(r).label === feedFilter)
                .slice(0, 5)
                .map((r) => {
                  const badge = runBadge(r);
                  return (
                    <li key={r.id} className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 p-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm">
                          <span className="font-semibold capitalize">{r.agentName}</span>{" "}
                          <span className="text-aether-muted">agent run {r.status}</span>
                        </p>
                        <p className="mono text-[11px] text-aether-muted-dim">
                          {r.startedAt ? new Date(r.startedAt).toLocaleString() : "queued"}
                        </p>
                      </div>
                      <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${badge.cls}`}>
                        {badge.label}
                      </span>
                    </li>
                  );
                })}
            </ul>
          )}
        </section>

        {/* Today's opportunities */}
        <section className="glass rounded-2xl border border-white/10 p-6" data-testid="todays-opportunities">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">Today&apos;s Opportunities</h2>
            <Link href="/dashboard/jobs" className="text-xs text-aether-muted transition hover:text-white">
              Browse all jobs
            </Link>
          </div>
          {jobs === null ? (
            <div className="grid gap-4 md:grid-cols-3" aria-busy="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="glass h-36 animate-pulse rounded-xl border border-white/10" />
              ))}
            </div>
          ) : jobs.length === 0 ? (
            <p className="py-4 text-center text-sm text-aether-muted-dim">
              No opportunities yet — run the Scout agent to discover jobs.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              {jobs.map((job) => (
                <article
                  key={job.id}
                  data-testid="opportunity-card"
                  className="glass group rounded-xl border border-white/10 p-4 transition hover:border-aether-coral/30"
                >
                  <div className="mb-3 flex items-center justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-xs font-bold">
                      {initials(job.company)}
                    </span>
                    {job.fitScore != null ? (
                      <span className="mono text-xs font-semibold text-aether-green">
                        {Math.round(Number(job.fitScore))}%
                      </span>
                    ) : null}
                  </div>
                  <h3 className="text-sm font-semibold leading-snug">{job.title}</h3>
                  <p className="mt-0.5 text-xs text-aether-muted">
                    {job.company}
                    {job.location ? ` · ${job.location}` : ""}
                  </p>
                  <Link
                    href="/dashboard/jobs"
                    className="mt-3 block w-full rounded-lg bg-aether-coral py-2 text-center text-xs font-medium text-white transition hover:opacity-90"
                  >
                    Tailor &amp; Apply
                  </Link>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Right 1/3 */}
      <div className="flex flex-col gap-7 xl:col-span-1">
        {/* Application funnel (DEF-014) */}
        <section className="glass rounded-2xl border border-white/10 p-6" data-testid="funnel-widget">
          <h2 className="mb-5 text-[15px] font-semibold">Application Funnel</h2>
          {funnel === null ? (
            <div className="h-40 animate-pulse rounded-xl border border-white/10" aria-busy="true" />
          ) : (
            <div className="flex flex-col gap-3">
              {FUNNEL_STAGES.map((stage) => {
                const value = Number(funnel[stage.key] ?? 0);
                const width = Math.max((value / maxStage) * 100, value > 0 ? 6 : 2);
                return (
                  <div key={stage.key}>
                    <div className="mb-1.5 flex justify-between text-xs">
                      <span className="text-aether-muted">{stage.label}</span>
                      <span className="mono font-medium">{value}</span>
                    </div>
                    <div className="h-2 rounded-full bg-white/5">
                      <div className={`h-2 rounded-full ${stage.color}`} style={{ width: `${width}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Needs Approval widget (wireframe dashboard.html) */}
        <section className="glass rounded-2xl border border-aether-amber/25 p-6" data-testid="needs-approval-widget">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">Needs Approval</h2>
            <Link href="/dashboard/approvals" className="flex items-center gap-1 text-xs text-aether-coral transition hover:text-white">
              Review <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
            </Link>
          </div>
          {pending.length === 0 ? (
            <p className="text-sm text-aether-muted-dim">
              Queue clear — nothing is waiting on you right now.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {pending.slice(0, 3).map((a) => {
                const payload = a.payload as { kind?: string; job_title?: string; company?: string };
                return (
                  <li key={a.id} className="rounded-xl border border-white/10 bg-white/5 p-3">
                    <p className="text-sm font-medium">
                      {payload.kind === "cover_letter" ? "Cover letter" : "Application"}
                      {payload.job_title ? ` — ${payload.job_title}` : ""}
                    </p>
                    <p className="mono mt-0.5 text-[11px] text-aether-muted-dim">
                      {payload.company ?? a.type} · {new Date(a.createdAt).toLocaleString()}
                    </p>
                  </li>
                );
              })}
              {pending.length > 3 ? (
                <li className="text-center text-xs text-aether-muted-dim">+{pending.length - 3} more waiting</li>
              ) : null}
            </ul>
          )}
        </section>

        {/* Recruiter CRM summary (DEF-015) */}
        <section
          className="glass rounded-2xl border border-white/10 p-6 transition hover:border-aether-coral/30"
          data-testid="crm-summary"
        >
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-aether-coral/25 bg-aether-coral/15">
                <i className="fa-solid fa-handshake text-xs text-aether-coral" aria-hidden="true" />
              </span>
              <h2 className="text-[15px] font-semibold">Recruiter CRM</h2>
            </div>
            <Link href="/dashboard/networking" className="flex items-center gap-1 text-xs text-aether-coral transition hover:text-white">
              Open <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
            </Link>
          </div>
          {crm === null ? (
            <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" />
          ) : (
            <div className="flex flex-col gap-2.5">
              <CrmRow icon="fa-comments" color="text-aether-green bg-aether-green/10" count={crm.activeConversations} label="active recruiter conversations" />
              <CrmRow icon="fa-clock" color="text-aether-amber bg-aether-amber/10" count={crm.followUpsDueToday} label="follow-ups due today" />
              <CrmRow icon="fa-user-plus" color="text-aether-violet bg-aether-violet/10" count={crm.warmIntrosPending} label="warm intro pending" />
            </div>
          )}
        </section>
      </div>

      {/* Market Intelligence (wireframe dashboard.html — static market snapshot) */}
      <section className="glass rounded-2xl border border-white/10 p-6 xl:col-span-3" data-testid="market-intelligence">
        <div className="mb-5 flex flex-wrap items-center gap-2.5">
          <span className="w-2 h-2 rounded-full bg-aether-violet live-dot" />
          <h2 className="text-[15px] font-semibold">Market Intelligence</h2>
          <span className="mono text-[11px] text-aether-muted-dim">Hiring &amp; recruitment trends · AU + US</span>
        </div>
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
              Demand Heatmap by Role
            </h3>
            <div className="mb-1.5 flex justify-end gap-4 pr-1 text-[10px] text-aether-muted-dim">
              <span>AU</span>
              <span>US</span>
            </div>
            <div className="space-y-2">
              {[
                { role: "AI / ML Engineer", au: 4, us: 4 },
                { role: "DevOps Engineer", au: 3, us: 3 },
                { role: "Technical Program Manager", au: 3, us: 4 },
                { role: "Solutions Architect", au: 2, us: 3 },
                { role: "Scrum Master", au: 1, us: 1 },
              ].map((r) => (
                <div key={r.role} className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs text-aether-muted">{r.role}</span>
                  <span className="flex shrink-0 gap-2">
                    {[r.au, r.us].map((v, i) => (
                      <span
                        key={i}
                        className={`h-4 w-6 rounded ${
                          v >= 4 ? "bg-aether-coral" : v === 3 ? "bg-aether-coral/60" : v === 2 ? "bg-aether-coral/30" : "bg-white/10"
                        }`}
                      />
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-5">
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
                Remote Work Index
              </h3>
              <div className="flex items-center gap-6">
                <div>
                  <p className="mono text-xl font-bold">35%</p>
                  <p className="text-[11px] text-aether-muted">🇦🇺 Australia</p>
                </div>
                <div>
                  <p className="mono text-xl font-bold">45%</p>
                  <p className="text-[11px] text-aether-muted">🌏 United States</p>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-aether-muted-dim">share of remote-friendly senior roles</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">Hot Sectors</h3>
              <div className="flex flex-wrap gap-1.5">
                {["Financial Services", "Government / Defence", "Healthcare AI", "Cloud Infrastructure", "Fintech"].map((sName) => (
                  <span key={sName} className="rounded-md border border-aether-violet/25 bg-aether-violet/10 px-2 py-0.5 text-[10px] text-aether-violet">
                    {sName}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">Salary Trends</h3>
            <div className="space-y-3">
              {[
                { role: "TPM", delta: "+6%", au: "AU $180–220K", us: "US $160–200K" },
                { role: "AI / ML Engineer", delta: "+18%", au: "AU $160–200K", us: "US $150–250K" },
                { role: "DevOps Engineer", delta: "+9%", au: "AU $150–190K", us: "US $118–174K" },
              ].map((r) => (
                <div key={r.role}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium">{r.role}</span>
                    <span className="mono font-semibold text-aether-green">{r.delta}</span>
                  </div>
                  <p className="mono text-[10px] text-aether-muted-dim">
                    {r.au} · {r.us}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-5">
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
                Best Time to Apply
              </h3>
              <p className="mono text-sm font-bold text-aether-green">+23% response rate</p>
              <p className="mt-1 text-[11px] text-aether-muted">
                Applications submitted Mon–Wed morning earn 23% higher response rates than the
                weekly average.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
                Where to Focus
              </h3>
              <p className="text-[11px] text-aether-muted">
                Your profile matches strongly for <span className="font-semibold text-white">TPM roles in Financial Services</span>.
                Consider expanding to <span className="font-semibold text-white">US remote opportunities</span>, where demand is{" "}
                <span className="font-semibold text-aether-green">40% higher</span>.
              </p>
              <Link href="/dashboard/jobs" className="mt-2 inline-block text-[11px] font-semibold text-aether-coral hover:underline">
                Explore matching roles →
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function CrmRow({ icon, color, count, label }: { icon: string; color: string; count: number; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${color}`}>
        <i className={`fa-solid ${icon} text-xs`} aria-hidden="true" />
      </span>
      <p className="text-sm text-aether-muted">
        <span className="mono font-semibold text-white">{count}</span> {label}
      </p>
    </div>
  );
}
