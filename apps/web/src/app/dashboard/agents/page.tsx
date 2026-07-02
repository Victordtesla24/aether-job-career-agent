"use client";

/**
 * Agents console — roster, run history and manual triggers backed by
 * GET /agents, GET /agents/runs and POST /agents/{name}/run.
 */
import { useCallback, useEffect, useState } from "react";

import {
  fetchAgentRuns,
  fetchAgents,
  runAgent,
  runPipeline,
  type AgentRun,
  type AgentSummary,
} from "../../../lib/api/agents";

const RUNNABLE = new Set(["scout", "fitScorer", "tailor", "coverLetter", "storyExtractor"]);

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

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [agentList, runList] = await Promise.all([fetchAgents(), fetchAgentRuns()]);
      setAgents(agentList);
      setRuns(runList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load agents");
      setAgents([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const trigger = async (name: string) => {
    setBusy(name);
    try {
      await runAgent(AGENT_ROUTE[name] ?? name, RUN_PARAMS[name] ?? {});
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Run failed for ${name}`);
    } finally {
      setBusy(null);
    }
  };

  const pipeline = async () => {
    setBusy("pipeline");
    try {
      await runPipeline();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pipeline run failed");
    } finally {
      setBusy(null);
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
          {busy === "pipeline" ? "Running Pipeline..." : "Run Full Pipeline"}
        </button>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
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
                  {agent.status}
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
                    {busy === agent.name ? "Running..." : "Run"}
                  </button>
                ) : null}
              </div>
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
