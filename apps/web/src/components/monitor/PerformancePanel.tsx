import type { Performance } from "./data";

export function PerformancePanel({ perf }: { perf: Performance }) {
  const metrics = [
    { value: perf.tasksDone.toLocaleString(), label: "tasks done", accent: "" },
    { value: perf.avgTime, label: "avg time", accent: "" },
    { value: perf.successRate, label: "success", accent: "text-aether-green" },
  ];
  return (
    <section aria-labelledby="monitor-perf-heading" className="glass rounded-2xl border border-white/10 p-5">
      <h2 id="monitor-perf-heading" className="text-sm font-semibold mb-4">
        Performance
      </h2>
      <dl className="grid grid-cols-3 gap-3 text-center">
        {metrics.map((m) => (
          <div key={m.label}>
            <dd className={`mono text-lg font-bold ${m.accent}`}>{m.value}</dd>
            <dt className="text-[10px] text-aether-muted-dim mt-1">{m.label}</dt>
          </div>
        ))}
      </dl>
    </section>
  );
}
