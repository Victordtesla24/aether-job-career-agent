"use client";

/**
 * Agent Monitor (AGT-MONITOR) — live orchestration view.
 *
 * Wireframe: design/screens/agent-monitor.html. Every panel is wired to real
 * data from `GET /agents` (roster) and `GET /agents/runs` (audit trail); the
 * derivation lives in ./data and is unit-tested. The view auto-refreshes on an
 * interval that "Pause All" stops, and the interval is torn down on unmount.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchAgentRuns,
  fetchAgents,
  type AgentRun,
  type AgentSummary,
} from "@/lib/api/agents";
import { ErrorLog } from "@/components/monitor/ErrorLog";
import { MonitorHeader } from "@/components/monitor/MonitorHeader";
import { PerformancePanel } from "@/components/monitor/PerformancePanel";
import { TaskQueue } from "@/components/monitor/TaskQueue";
import { WorkflowGraph } from "@/components/monitor/WorkflowGraph";
import {
  anyRunning,
  deriveErrorLog,
  deriveHeaderStats,
  derivePerformance,
  deriveTaskQueue,
  mapAgentsToNodes,
} from "@/components/monitor/data";

const POLL_MS = 5000;

interface Snapshot {
  agents: AgentSummary[];
  runs: AgentRun[];
}

export default function AgentMonitorPage() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  // Monotonic request id: overlapping loads (mount, poll ticks, retry) must not
  // let a slower, older response overwrite a newer snapshot.
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const [agents, runs] = await Promise.all([fetchAgents(), fetchAgentRuns({})]);
      if (seq !== requestSeq.current) return;
      setData({ agents, runs });
      setError(null);
    } catch (e) {
      if (seq !== requestSeq.current) return;
      setError(e instanceof Error ? e.message : "Failed to load orchestration data");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (paused) return;
    timer.current = setInterval(() => void load(), POLL_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
    };
  }, [paused, load]);

  if (error && data === null) {
    return (
      <div className="flex flex-col gap-6">
        <section
          role="alert"
          className="glass rounded-2xl border border-red-500/30 bg-red-500/5 p-8 text-center"
        >
          <i className="fa-solid fa-triangle-exclamation text-red-400 text-2xl mb-3" aria-hidden="true" />
          <h2 className="text-lg font-semibold">Couldn’t reach the orchestrator</h2>
          <p className="mt-2 text-sm text-aether-muted">{error}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-5 inline-flex items-center gap-2 text-xs font-medium py-2.5 px-4 rounded-lg bg-aether-coral/12 hover:bg-aether-coral/20 border border-aether-coral/20 text-white transition"
          >
            <i className="fa-solid fa-rotate-right" aria-hidden="true" />
            Retry
          </button>
        </section>
      </div>
    );
  }

  const stats = data ? deriveHeaderStats(data.agents, data.runs) : null;
  const nodes = data ? mapAgentsToNodes(data.agents) : [];
  const live = !paused && data !== null && anyRunning(data.runs);

  return (
    <div className="flex flex-col gap-6">
      <MonitorHeader stats={stats} paused={paused} onTogglePause={() => setPaused((p) => !p)} />

      {error && data !== null ? (
        <section
          role="alert"
          className="glass flex items-center justify-between gap-4 rounded-xl border border-red-500/30 bg-red-500/5 p-4"
        >
          <p className="text-sm text-red-300">
            <i className="fa-solid fa-triangle-exclamation mr-2" aria-hidden="true" />
            Live updates interrupted — showing last known state. {error}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex shrink-0 items-center gap-2 text-xs font-medium py-2 px-3 rounded-lg bg-aether-coral/12 hover:bg-aether-coral/20 border border-aether-coral/20 text-white transition"
          >
            <i className="fa-solid fa-rotate-right" aria-hidden="true" />
            Retry
          </button>
        </section>
      ) : null}

      {data === null ? (
        <MonitorSkeleton />
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <WorkflowGraph nodes={nodes} live={live} paused={paused} />
          <div className="flex flex-col gap-5 xl:col-span-1">
            <TaskQueue items={deriveTaskQueue(data.runs)} />
            <PerformancePanel perf={derivePerformance(data.runs)} />
            <ErrorLog entries={deriveErrorLog(data.runs)} />
          </div>
        </div>
      )}
    </div>
  );
}

function MonitorSkeleton() {
  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-6" aria-busy="true">
      <div className="glass h-[520px] animate-pulse rounded-2xl border border-white/10 xl:col-span-2" />
      <div className="flex flex-col gap-5">
        {[0, 1, 2].map((i) => (
          <div key={i} className="glass h-40 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </div>
    </div>
  );
}
