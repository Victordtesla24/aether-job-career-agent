"use client";

/**
 * Agents console — roster, run history and manual triggers backed by
 * GET /agents, GET /agents/runs, POST /agents/{name}/run and
 * POST /agents/pipeline/run.
 *
 * UX contract (defect fix): every trigger gives immediate feedback, live
 * progress while it runs (the pipeline call is synchronous and can take
 * 30–120 s), and a completion/failure message that tells the user where
 * the data landed (Jobs, Resume Studio, Approvals, Story Bank).
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchAgentRuns,
  fetchAgents,
  runAgent,
  runPipeline,
  type AgentRun,
  type AgentSummary,
} from "../../../lib/api/agents";
import { apiRequest } from "../../../lib/api/client";
import {
  agentSuccessNotice,
  pipelineCompletionNotice,
  pipelineProgressNotice,
  pipelineStartNotice,
  runErrorNotice,
  type Notice,
} from "../../../lib/agents-feedback";

const RUNNABLE = new Set(["scout", "fitScorer", "tailor", "coverLetter", "storyExtractor"]);

/** Registry-only nodes that execute inside the pipeline, not standalone. */
const PIPELINE_ONLY: Record<string, string> = {
  supervisor: "Plans the run — executes inside the full pipeline",
  matcher: "Picks the top-fit job — executes inside the full pipeline",
};

const RUN_PARAMS: Record<string, Record<string, unknown>> = {
  scout: { query: "software engineer", location: "Australia" },
};

const AGENT_ROUTE: Record<string, string> = {
  scout: "scout",
  fitScorer: "fit-scorer",
  tailor: "tailor",
  coverLetter: "cover-letter",
  storyExtractor: "story-extractor",
};

const POLL_MS = 3000;

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const runStartedAt = useRef<number>(0);

  const load = useCallback(async () => {
    try {
      const [agentList, runList] = await Promise.all([fetchAgents(), fetchAgentRuns()]);
      setAgents(agentList);
      setRuns(runList);
    } catch (e) {
      setNotice(runErrorNotice(e, "Loading agents"));
      setAgents((prev) => prev ?? []);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  /** Poll runs while the pipeline call is in flight so the RECENT RUNS
   *  table and agent cards update live, and the banner shows which agent
   *  is currently working. */
  const startPolling = useCallback(
    (mode: "pipeline" | "agent") => {
      runStartedAt.current = Date.now();
      stopPolling();
      pollTimer.current = setInterval(() => {
        void (async () => {
          try {
            const [agentList, runList] = await Promise.all([fetchAgents(), fetchAgentRuns()]);
            setAgents(agentList);
            setRuns(runList);
            if (mode === "pipeline") {
              const completedSinceStart = runList
                .filter(
                  (r) =>
                    r.status === "completed" &&
                    r.createdAt &&
                    new Date(r.createdAt).getTime() >= runStartedAt.current,
                )
                .map((r) => r.agentName);
              setNotice(pipelineProgressNotice(completedSinceStart));
            }
          } catch {
            /* transient poll failure — keep the last notice */
          }
        })();
      }, POLL_MS);
    },
    [stopPolling],
  );

  const pipeline = async () => {
    setBusy("pipeline");
    setNotice(pipelineStartNotice());
    startPolling("pipeline");
    try {
      const result = await runPipeline();
      setNotice(pipelineCompletionNotice(result));
    } catch (e) {
      setNotice(runErrorNotice(e, "Pipeline"));
    } finally {
      stopPolling();
      setBusy(null);
      await load();
    }
  };

  /** Tailor/CoverLetter need a job target: use the top job by fit score.
   *  (Previously these buttons sent an empty body → guaranteed 422.) */
  const resolveParams = async (name: string): Promise<Record<string, unknown>> => {
    if (name === "tailor" || name === "coverLetter") {
      const jobs = await apiRequest<Array<{ id: string }>>("/jobs?sort=fitScore");
      if (jobs.length === 0) {
        throw Object.assign(new Error("No jobs discovered yet"), { status: 422 });
      }
      return { job_id: jobs[0].id };
    }
    return RUN_PARAMS[name] ?? {};
  };

  const trigger = async (name: string) => {
    setBusy(name);
    setNotice({ kind: "info", text: `${name} started — running now…` });
    startPolling("agent");
    try {
      const params = await resolveParams(name);
      const output = await runAgent(AGENT_ROUTE[name] ?? name, params);
      setNotice(agentSuccessNotice(name, output));
    } catch (e) {
      setNotice(runErrorNotice(e, name));
    } finally {
      stopPolling();
      setBusy(null);
      await load();
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Agents</h1>
          <p className="text-sm text-aether-muted">
            The Aether crew — approval-gated agents never act without you.
          </p>
        </div>
        <button
          type="button"
          data-testid="run-pipeline-btn"
          onClick={() => void pipeline()}
          disabled={busy !== null}
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {busy === "pipeline" ? (
            <span className="inline-flex items-center gap-2">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              Running Pipeline…
            </span>
          ) : (
            "Run Full Pipeline"
          )}
        </button>
      </header>

      {notice ? (
        <p
          data-testid="agents-notice"
          role="status"
          className={`rounded-xl border p-3 text-sm ${
            notice.kind === "error"
              ? "border-red-500/30 bg-red-500/10 text-red-300"
              : notice.kind === "success"
                ? "border-aether-green/30 bg-aether-green/10 text-aether-green"
                : "border-aether-amber/30 bg-aether-amber/10 text-aether-amber"
          }`}
        >
          {notice.kind === "info" && busy !== null ? (
            <span className="mr-2 inline-block h-3 w-3 animate-spin rounded-full border-2 border-current/40 border-t-current align-middle" />
          ) : null}
          {notice.text}
          {notice.href ? (
            <>
              {" "}
              <Link href={notice.href} className="font-semibold underline underline-offset-2">
                {notice.hrefLabel ?? notice.href}
              </Link>
            </>
          ) : null}
        </p>
      ) : null}

      {agents === null ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="glass h-32 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent) => (
            <article
              key={agent.name}
              data-testid="agent-card"
              className="glass rounded-2xl border border-white/10 p-5 transition hover:border-white/20"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold capitalize">{agent.name}</h2>
                  <p className="mt-0.5 text-xs text-aether-muted">
                    {agent.last_run
                      ? `Last run ${new Date(agent.last_run).toLocaleString()}`
                      : "Never run"}
                  </p>
                </div>
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs ${
                    agent.status === "idle"
                      ? "border-white/10 text-aether-muted-dim"
                      : "border-aether-green/40 text-aether-green"
                  }`}
                >
                  {busy === "pipeline" && agent.name in PIPELINE_ONLY ? "in pipeline" : agent.status}
                </span>
              </div>
              <div className="mt-3 flex items-center justify-between">
                {agent.approval_gated ? (
                  <span className="text-xs text-aether-amber">🔒 approval gated</span>
                ) : (
                  <span className="text-xs text-aether-muted-dim">autonomous</span>
                )}
                {RUNNABLE.has(agent.name) ? (
                  <button
                    type="button"
                    data-testid={`run-agent-${agent.name}`}
                    onClick={() => void trigger(agent.name)}
                    disabled={busy !== null}
                    className="rounded-lg border border-white/15 px-3 py-1 text-xs font-semibold hover:border-white/30 disabled:opacity-50"
                  >
                    {busy === agent.name ? "Running…" : "Run"}
                  </button>
                ) : null}
              </div>
              {agent.name in PIPELINE_ONLY ? (
                <p className="mt-2 text-xs text-aether-muted-dim" data-testid="pipeline-only-note">
                  {PIPELINE_ONLY[agent.name]} — use “Run Full Pipeline”.
                </p>
              ) : null}
            </article>
          ))}
        </div>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
          Recent runs
        </h2>
        {runs.length === 0 ? (
          <div className="glass rounded-2xl border border-white/10 p-6 text-center text-sm text-aether-muted">
            No agent runs recorded yet.
          </div>
        ) : (
          <div className="glass overflow-x-auto rounded-2xl border border-white/10">
            <table className="w-full text-left text-sm" data-testid="agent-runs-table">
              <thead className="text-xs uppercase tracking-wide text-aether-muted-dim">
                <tr className="border-b border-white/10">
                  <th className="px-4 py-3">Agent</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 20).map((run) => (
                  <tr key={run.id} className="border-b border-white/5 last:border-0">
                    <td className="px-4 py-2.5 font-medium">{run.agentName}</td>
                    <td className="px-4 py-2.5">
                      <span
                        className={
                          run.status === "completed"
                            ? "text-aether-green"
                            : run.status === "failed"
                              ? "text-red-300"
                              : "text-aether-amber"
                        }
                      >
                        {run.status}
                      </span>
                    </td>
                    <td className="mono px-4 py-2.5 text-xs text-aether-muted">
                      {run.startedAt ? new Date(run.startedAt).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-aether-muted-dim">
                      {run.error ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
