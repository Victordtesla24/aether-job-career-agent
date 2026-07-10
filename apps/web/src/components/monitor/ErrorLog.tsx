import type { LogEntry, LogLevel } from "./data";

const LEVEL_COLOR: Record<LogLevel, string> = {
  ERR: "text-red-400",
  WRN: "text-aether-yellow",
  OK: "text-aether-green",
};

export function ErrorLog({ entries }: { entries: LogEntry[] }) {
  return (
    <section
      aria-labelledby="monitor-log-heading"
      className="glass rounded-2xl border border-white/10 p-5 flex-1 overflow-hidden"
    >
      <div className="flex items-center gap-2 mb-3">
        <i className="fa-solid fa-triangle-exclamation text-red-400 text-xs" aria-hidden="true" />
        <h2 id="monitor-log-heading" className="text-sm font-semibold">
          Error Log
        </h2>
      </div>
      {entries.length === 0 ? (
        <p className="text-xs text-aether-muted-dim">No agent activity recorded yet.</p>
      ) : (
        <ul className="flex flex-col gap-2 mono text-[11px]">
          {entries.map((e) => (
            <li key={e.id} className="flex gap-2">
              <span className={LEVEL_COLOR[e.level]}>{e.level}</span>
              <span className="text-aether-muted-dim shrink-0">{e.time}</span>
              <span className="text-aether-muted truncate">{e.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
