import type { QueueItem } from "./data";

export function TaskQueue({ items }: { items: QueueItem[] }) {
  return (
    <section aria-labelledby="monitor-queue-heading" className="glass rounded-2xl border border-white/10 p-5">
      <h2 id="monitor-queue-heading" className="text-sm font-semibold mb-4">
        Task Queue
      </h2>
      {items.length === 0 ? (
        <p className="text-xs text-aether-muted-dim">No tasks in flight — the queue is clear.</p>
      ) : (
        <ul className="flex flex-col gap-3.5">
          {items.map((item) => {
            const running = item.status === "running";
            return (
              <li key={item.id}>
                <div className="flex justify-between text-xs mb-1.5">
                  <span>{item.label}</span>
                  <span className={`mono ${running ? "text-aether-coral" : "text-aether-yellow"}`}>
                    {running ? "running" : "queued"}
                  </span>
                </div>
                <div
                  className="h-1.5 rounded-full bg-white/8 overflow-hidden"
                  role="progressbar"
                  aria-label={`${item.label} ${item.status}`}
                  {...(running ? {} : { "aria-valuenow": 0, "aria-valuemin": 0, "aria-valuemax": 100 })}
                >
                  <div
                    className={
                      running
                        ? "h-1.5 w-2/5 rounded-full bg-aether-coral monitor-indeterminate"
                        : "h-1.5 w-full rounded-full bg-aether-yellow/30"
                    }
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <style>{`@keyframes monitor-indeterminate{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}.monitor-indeterminate{animation:monitor-indeterminate 1.4s ease-in-out infinite}@media (prefers-reduced-motion: reduce){.monitor-indeterminate{animation:none}}`}</style>
    </section>
  );
}
