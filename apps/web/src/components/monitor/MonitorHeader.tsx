import Link from "next/link";

import type { HeaderStats } from "./data";

export function MonitorHeader({
  stats,
  paused,
  onTogglePause,
}: {
  stats: HeaderStats | null;
  paused: boolean;
  onTogglePause: () => void;
}) {
  return (
    <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 className="text-[15px] font-semibold">Agent Orchestration</h1>
        <p role="status" aria-live="polite" className="text-xs text-aether-muted-dim mono">
          {stats
            ? `${stats.agentsOnline} agents online · ${stats.tasksInQueue} tasks in queue · ${stats.successRate} success`
            : "loading orchestration status…"}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onTogglePause}
          aria-pressed={paused}
          className="flex items-center gap-2 text-xs font-medium px-3.5 py-2 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition"
        >
          <i className={`fa-solid ${paused ? "fa-play" : "fa-pause"} text-[10px]`} aria-hidden="true" />
          {paused ? "Resume Live" : "Pause All"}
        </button>
        <Link
          href="/dashboard/agents"
          className="flex items-center gap-2 text-xs font-medium px-3.5 py-2 rounded-lg bg-aether-coral hover:opacity-90 text-white transition"
        >
          <i className="fa-solid fa-hand text-[10px]" aria-hidden="true" />
          Manual Override
        </Link>
      </div>
    </header>
  );
}
