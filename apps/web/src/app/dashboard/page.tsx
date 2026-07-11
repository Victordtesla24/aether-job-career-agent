"use client";

/**
 * Dashboard home (wireframe design/screens/dashboard.html): live stat cards,
 * agent activity feed, today's top opportunities, the Application Funnel,
 * Story Bank quick access, Recruiter CRM summary, the Needs Approval queue
 * (approve/reject wired to POST /approvals — REQ-TM-05/J4) and the Market
 * Intelligence snapshot. Every figure hydrates from the live API per
 * REQ-TM-10 — nothing is hardcoded (funnel is data-driven per audit D11).
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import DashboardStats from "../../components/dashboard/DashboardStats";
import MarketPulse from "../../components/analytics/MarketPulse";
import {
  agentDisplayName,
  agentTile,
  describeRun,
  relTime,
  runBadge,
} from "../../components/dashboard/feed";
import { fetchAgentRuns, type AgentRun } from "../../lib/api/agents";
import { fetchFunnel, type Funnel } from "../../lib/api/analytics";
import {
  approveRequest,
  fetchApprovals,
  rejectRequest,
  type Approval,
} from "../../lib/api/approvals";
import { apiRequest } from "../../lib/api/client";
import type { Job } from "../../lib/api/jobs";
import { fetchStories, type Story } from "../../lib/api/stories";
import { fetchNetworkingSummary, type NetworkingSummary } from "../../lib/api/workspaces";

/** /jobs rows carry salary columns the shared zod schema doesn't surface. */
type DashboardJob = Job & {
  salaryMin?: number | null;
  salaryMax?: number | null;
  currency?: string | null;
};

const FUNNEL_STAGES: Array<{ key: keyof Funnel & string; label: string; color: string }> = [
  { key: "jobs_found", label: "Jobs Found", color: "bg-aether-indigo" },
  { key: "applied", label: "Applied", color: "bg-aether-indigo/80" },
  { key: "screened", label: "Screened", color: "bg-aether-coral" },
  { key: "interviewed", label: "Interviewed", color: "bg-aether-amber" },
  { key: "offers", label: "Offers", color: "bg-aether-green" },
];

const FEED_FILTERS = ["All", "Discovered", "Tailored", "Submitted", "Waiting"] as const;

function initials(company: string) {
  const parts = company.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "•";
  return parts
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function salaryLabel(job: DashboardJob): string {
  if (job.salaryMin != null && job.salaryMax != null) {
    const k = (n: number) => `$${Math.round(n / 1000)}k`;
    return `${k(job.salaryMin)} – ${k(job.salaryMax)}`;
  }
  return `via ${job.source}`;
}

/** Approval card title from the gated action payload. */
function approvalTitle(a: Approval): string {
  const kind = (a.payload as { kind?: string }).kind;
  if (kind === "cover_letter") return "Send cover letter";
  if (a.type === "email_send") return "Send email";
  if (a.type === "offer_response") return "Respond to offer";
  return "Submit application";
}

/** Load-once state with an explicit error channel (no fake-empty states). */
function useLoad<T>(load: () => Promise<T>): {
  data: T | null;
  error: string | null;
  setData: (value: T) => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    let alive = true;
    loadRef
      .current()
      .then((value) => {
        if (alive) setData(value);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : "request failed");
      });
    return () => {
      alive = false;
    };
  }, []);
  return { data, error, setData };
}

function WidgetError({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
      {children}
    </p>
  );
}

export default function DashboardPage() {
  const funnel = useLoad<Funnel>(() => fetchFunnel("all"));
  const weekly = useLoad<Funnel>(() => fetchFunnel("7d"));
  const jobs = useLoad<DashboardJob[]>(() => apiRequest<DashboardJob[]>("/jobs?sort=fitScore"));
  const runs = useLoad<AgentRun[]>(() => fetchAgentRuns());
  const stories = useLoad<Story[]>(() => fetchStories());
  const crm = useLoad<NetworkingSummary["crmSummary"]>(() =>
    fetchNetworkingSummary().then((n) => n.crmSummary),
  );
  const approvals = useLoad<Approval[]>(() => fetchApprovals("pending"));

  const [feedFilter, setFeedFilter] = useState<(typeof FEED_FILTERS)[number]>("All");
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);
  const [approvalActionError, setApprovalActionError] = useState<string | null>(null);

  const scoredJobs = (jobs.data ?? []).filter((j) => j.fitScore != null);
  const avgFit =
    scoredJobs.length > 0
      ? scoredJobs.reduce((sum, j) => sum + Number(j.fitScore), 0) / scoredJobs.length
      : null;
  const topJobs = (jobs.data ?? []).slice(0, 3);
  const maxStage = funnel.data ? Math.max(funnel.data.jobs_found, 1) : 1;
  const pending = approvals.data ?? [];

  async function resolveApproval(id: string, action: "approve" | "reject") {
    setBusyApprovalId(id);
    setApprovalActionError(null);
    try {
      await (action === "approve" ? approveRequest(id) : rejectRequest(id));
      approvals.setData(pending.filter((a) => a.id !== id));
    } catch (e: unknown) {
      setApprovalActionError(
        `Couldn't ${action} — ${e instanceof Error ? e.message : "request failed"}`,
      );
    } finally {
      setBusyApprovalId(null);
    }
  }

  const visibleRuns = (runs.data ?? [])
    .filter((r) => feedFilter === "All" || runBadge(r).label === feedFilter)
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-7">
      {/* Stats row — full width above the columns (wireframe stats-row-p7q8r9) */}
      <DashboardStats
        funnel={funnel.data}
        extras={{ weeklyApplied: weekly.data?.applied ?? null, avgFit }}
        error={funnel.error}
      />

      <div className="grid gap-7 xl:grid-cols-3">
        {/* Left 2/3 */}
        <div className="flex min-w-0 flex-col gap-7 xl:col-span-2">
          {/* Agent activity feed (agent-feed-s1t2u3) */}
          <section className="glass rounded-2xl border border-white/10 p-6" data-testid="agent-feed">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="live-dot h-2 w-2 rounded-full bg-aether-green" />
                <h2 className="text-[15px] font-semibold">Agent Activity</h2>
                <span className="mono text-[11px] text-aether-muted-dim">live</span>
              </div>
              <Link
                href="/dashboard/agents"
                className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center text-xs text-aether-coral transition hover:text-white"
              >
                View all
              </Link>
            </div>
            <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Filter agent activity">
              {FEED_FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  aria-pressed={feedFilter === f}
                  onClick={() => setFeedFilter(f)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] transition max-sm:min-h-11 max-sm:px-4 ${
                    feedFilter === f
                      ? "border-aether-coral/50 bg-aether-coral/15 font-semibold text-aether-coral"
                      : "border-white/10 text-aether-muted hover:text-white"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            {runs.error ? (
              <WidgetError>Couldn&apos;t load agent activity — {runs.error}</WidgetError>
            ) : runs.data === null ? (
              <div className="space-y-2.5" aria-busy="true" aria-label="Loading agent activity">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-14 animate-pulse rounded-xl border border-white/10 bg-white/5" />
                ))}
              </div>
            ) : runs.data.length === 0 ? (
              <p className="text-sm text-aether-muted">
                No agent activity yet — head to the{" "}
                <Link href="/dashboard/agents" className="text-aether-coral underline underline-offset-2">
                  Agents workspace
                </Link>{" "}
                to launch the discovery → tailoring pipeline. Anything that leaves the system
                waits for your approval first.
              </p>
            ) : visibleRuns.length === 0 ? (
              <p className="py-2 text-sm text-aether-muted-dim">
                No “{feedFilter}” activity in the latest runs.
              </p>
            ) : (
              <ul className="space-y-3">
                {visibleRuns.map((r) => {
                  const badge = runBadge(r);
                  const tile = agentTile(r.agentName);
                  const desc = describeRun(r);
                  return (
                    <li key={r.id} className="flex items-start gap-3.5">
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${tile.cls}`}
                      >
                        <i className={`fa-solid ${tile.icon} text-xs`} aria-hidden="true" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">
                          <span className="font-medium">{agentDisplayName(r.agentName)}</span>{" "}
                          {desc.text}
                          {desc.highlight ? <span className="text-white">{desc.highlight}</span> : null}
                        </p>
                        <p className="mono mt-1 text-[11px] text-aether-muted-dim">
                          {relTime(r.startedAt ?? r.createdAt)}
                          {desc.metric ? ` · ${desc.metric}` : ""}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-medium ${badge.cls}`}
                      >
                        {badge.label}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Today's opportunities (opportunities-v4w5x6) */}
          <section className="glass rounded-2xl border border-white/10 p-6" data-testid="todays-opportunities">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Today&apos;s Opportunities</h2>
              <Link href="/dashboard/jobs" className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center text-xs text-aether-muted transition hover:text-white">
                Browse all jobs
              </Link>
            </div>
            {jobs.error ? (
              <WidgetError>Couldn&apos;t load opportunities — {jobs.error}</WidgetError>
            ) : jobs.data === null ? (
              <div className="grid gap-4 md:grid-cols-3" aria-busy="true" aria-label="Loading opportunities">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="glass h-40 animate-pulse rounded-xl border border-white/10" />
                ))}
              </div>
            ) : topJobs.length === 0 ? (
              <p className="py-4 text-center text-sm text-aether-muted-dim">
                No opportunities yet — run the Scout agent to discover jobs.
              </p>
            ) : (
              <div className="grid gap-4 md:grid-cols-3">
                {topJobs.map((job, idx) => (
                  <article
                    key={job.id}
                    data-testid="opportunity-card"
                    className="glass group flex flex-col rounded-xl border border-white/10 p-4 transition hover:border-aether-coral/30"
                  >
                    <div className="mb-3 flex items-center justify-between">
                      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-xs font-bold">
                        {initials(job.company)}
                      </span>
                      {job.fitScore != null ? (
                        <span
                          className={`mono text-xs font-semibold ${
                            Number(job.fitScore) >= 85 ? "text-aether-green" : "text-aether-yellow"
                          }`}
                        >
                          {Math.round(Number(job.fitScore))}%
                        </span>
                      ) : null}
                    </div>
                    <h3 className="text-sm font-semibold leading-snug">{job.title}</h3>
                    <p className="mt-0.5 text-xs text-aether-muted">
                      {job.company}
                      {job.location ? ` · ${job.location}` : ""}
                    </p>
                    <p className="mono mt-2 text-xs text-aether-muted-dim">{salaryLabel(job)}</p>
                    {idx === 0 ? (
                      <Link
                        href={`/dashboard/resume?job=${job.id}`}
                        className="mt-3 block w-full rounded-lg bg-aether-coral py-2 text-center text-xs font-medium text-white transition hover:opacity-90 max-sm:min-h-11 max-sm:content-center"
                      >
                        Tailor &amp; Apply
                      </Link>
                    ) : (
                      <Link
                        href="/dashboard/jobs"
                        className="mt-3 block w-full rounded-lg border border-white/10 bg-white/5 py-2 text-center text-xs font-medium transition hover:bg-white/10 max-sm:min-h-11 max-sm:content-center"
                      >
                        Review Match
                      </Link>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Right 1/3 */}
        <div className="flex min-w-0 flex-col gap-7 xl:col-span-1">
          {/* Application funnel (funnel-q7r8s9 — data-driven per audit D11) */}
          <section className="glass rounded-2xl border border-white/10 p-6" data-testid="funnel-widget">
            <h2 className="mb-5 text-[15px] font-semibold">Application Funnel</h2>
            {funnel.error ? (
              <WidgetError>Couldn&apos;t load the funnel — {funnel.error}</WidgetError>
            ) : funnel.data === null ? (
              <div className="h-40 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading funnel" />
            ) : (
              <div className="flex flex-col gap-3">
                {FUNNEL_STAGES.map((stage) => {
                  const value = Number(funnel.data?.[stage.key] ?? 0);
                  const width = value > 0 ? Math.max((value / maxStage) * 100, 4) : 0;
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

          {/* Story Bank quick access (story-bank-quick-db10) */}
          <section
            className="glass rounded-2xl border border-white/10 p-6 transition hover:border-aether-indigo/30"
            data-testid="story-bank-widget"
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-aether-indigo/25 bg-aether-indigo/15">
                  <i className="fa-solid fa-book-bookmark text-xs text-[#818CF8]" aria-hidden="true" />
                </span>
                <h2 className="text-[15px] font-semibold">Story Bank</h2>
              </div>
              <Link
                href="/dashboard/stories"
                className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center flex items-center gap-1 text-xs text-[#818CF8] transition hover:text-white"
              >
                Open <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
              </Link>
            </div>
            {stories.error ? (
              <WidgetError>Couldn&apos;t load stories — {stories.error}</WidgetError>
            ) : stories.data === null ? (
              <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading stories" />
            ) : stories.data.length === 0 ? (
              <p className="text-sm text-aether-muted-dim">
                No STAR stories yet —{" "}
                <Link href="/dashboard/stories" className="text-aether-coral underline underline-offset-2">
                  capture your first achievement
                </Link>
                .
              </p>
            ) : (
              <>
                <p className="mb-4 text-sm text-[#C8C8DC]">
                  <span className="mono font-bold text-white">{stories.data.length}</span> STAR
                  achievement{stories.data.length === 1 ? "" : "s"} ready to deploy
                </p>
                <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-aether-muted-dim">
                  Recently used
                </p>
                <ul className="flex flex-col gap-2">
                  {stories.data.slice(0, 3).map((s) => (
                    <li
                      key={s.id}
                      className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2"
                    >
                      <span className="truncate text-xs text-[#C8C8DC]">{s.title}</span>
                      <span className="mono ml-2 shrink-0 rounded bg-aether-coral/15 px-1.5 py-0.5 text-[10px] text-aether-coral">
                        {s.usedInResumes ?? 0} maps
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          {/* Recruiter CRM summary (crm-summary-db11) */}
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
              <Link
                href="/dashboard/networking"
                className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center flex items-center gap-1 text-xs text-aether-coral transition hover:text-white"
              >
                Open <i className="fa-solid fa-arrow-right text-[9px]" aria-hidden="true" />
              </Link>
            </div>
            {crm.error ? (
              <WidgetError>Couldn&apos;t load CRM summary — {crm.error}</WidgetError>
            ) : crm.data === null ? (
              <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading CRM summary" />
            ) : (
              <div className="flex flex-col gap-2.5">
                <CrmRow
                  icon="fa-comments"
                  color="text-aether-green bg-aether-green/10"
                  count={crm.data.activeConversations}
                  label="active recruiter conversations"
                />
                <CrmRow
                  icon="fa-clock"
                  color="text-aether-yellow bg-aether-yellow/10"
                  count={crm.data.followUpsDueToday}
                  label="follow-ups due today"
                />
                <CrmRow
                  icon="fa-user-plus"
                  color="text-[#818CF8] bg-aether-indigo/10"
                  count={crm.data.warmIntrosPending}
                  label="warm intro pending"
                />
              </div>
            )}
          </section>

          {/* Needs Approval (approvals-t1u2v3, REQ-TM-05/J4) */}
          <section
            className="glass flex-1 rounded-2xl border border-white/10 p-6"
            data-testid="needs-approval-widget"
          >
            <div className="mb-4 flex items-center gap-2">
              <i className="fa-solid fa-shield-halved text-sm text-aether-yellow" aria-hidden="true" />
              <h2 className="text-[15px] font-semibold">Needs Approval</h2>
              <span
                className="ml-auto rounded-full bg-aether-yellow/15 px-2 py-0.5 text-[10px] font-semibold text-aether-yellow"
                data-testid="approval-count"
              >
                {pending.length}
              </span>
            </div>
            {approvalActionError ? (
              <p role="alert" className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300">
                {approvalActionError}
              </p>
            ) : null}
            {approvals.error ? (
              <WidgetError>Couldn&apos;t load the approval queue — {approvals.error}</WidgetError>
            ) : approvals.data === null ? (
              <div className="h-24 animate-pulse rounded-xl border border-white/10" aria-busy="true" aria-label="Loading approvals" />
            ) : pending.length === 0 ? (
              <p className="text-sm text-aether-muted-dim">
                Queue clear — nothing is waiting on you right now.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {pending.slice(0, 3).map((a) => {
                  const payload = a.payload as { job_title?: string; company?: string };
                  const title = approvalTitle(a);
                  const subtitle = [payload.job_title, payload.company].filter(Boolean).join(" · ");
                  const busy = busyApprovalId === a.id;
                  return (
                    <li key={a.id} className="rounded-xl border border-white/10 bg-white/5 p-4">
                      <p className="text-sm font-medium">{title}</p>
                      {subtitle ? <p className="mt-0.5 text-xs text-aether-muted">{subtitle}</p> : null}
                      <p className="mono mt-2 text-[11px] text-aether-muted-dim">
                        requested {relTime(a.createdAt)} · waiting on you
                      </p>
                      <div className="mt-3 flex gap-2">
                        <button
                          type="button"
                          disabled={busy}
                          aria-label={`Approve: ${title}${subtitle ? ` — ${subtitle}` : ""}`}
                          onClick={() => void resolveApproval(a.id, "approve")}
                          className="flex-1 rounded-lg border border-aether-green/25 bg-aether-green/15 py-2 text-xs font-medium text-aether-green transition hover:bg-aether-green/25 disabled:cursor-not-allowed disabled:opacity-50 max-sm:min-h-11"
                        >
                          {busy ? "Working…" : "Approve"}
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          aria-label={`Reject: ${title}${subtitle ? ` — ${subtitle}` : ""}`}
                          onClick={() => void resolveApproval(a.id, "reject")}
                          className="flex-1 rounded-lg border border-white/10 bg-white/5 py-2 text-xs font-medium text-aether-muted transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50 max-sm:min-h-11"
                        >
                          Reject
                        </button>
                      </div>
                    </li>
                  );
                })}
                {pending.length > 3 ? (
                  <li className="text-center text-xs text-aether-muted-dim">
                    <Link
                      href="/dashboard/approvals"
                      className="max-sm:min-h-11 max-sm:px-3 max-sm:inline-flex max-sm:items-center hover:text-white"
                    >
                      +{pending.length - 3} more waiting — review all
                    </Link>
                  </li>
                ) : null}
              </ul>
            )}
          </section>
        </div>
      </div>

      {/* Market Intelligence (market-intel-mi01) */}
      <MarketPulse />
    </div>
  );
}

function CrmRow({
  icon,
  color,
  count,
  label,
}: {
  icon: string;
  color: string;
  count: number;
  label: string;
}) {
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
