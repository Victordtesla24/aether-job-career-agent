import { WORKFLOW_EDGES, type NodeState, type NodeTone } from "./data";

const TONE: Record<NodeTone, { border: string; iconBg: string; icon: string; text: string }> = {
  green: { border: "border-aether-green/40", iconBg: "bg-aether-green/15", icon: "text-aether-green", text: "text-aether-green" },
  coral: { border: "border-aether-coral/50", iconBg: "bg-aether-coral/20", icon: "text-aether-coral", text: "text-aether-coral" },
  yellow: { border: "border-aether-yellow/40", iconBg: "bg-aether-yellow/15", icon: "text-aether-yellow", text: "text-aether-yellow" },
  red: { border: "border-red-500/50", iconBg: "bg-red-500/15", icon: "text-red-400", text: "text-red-400" },
  dim: { border: "border-white/12", iconBg: "bg-white/8", icon: "text-aether-muted", text: "text-aether-muted-dim" },
};

export function WorkflowGraph({ nodes, live }: { nodes: NodeState[]; live: boolean }) {
  const byId = new Map(nodes.map((n) => [n.id, n]));

  return (
    <section
      aria-labelledby="monitor-graph-heading"
      className="glass rounded-2xl border border-white/10 p-6 xl:col-span-2"
    >
      <div className="flex items-center justify-between mb-2">
        <h2 id="monitor-graph-heading" className="text-[15px] font-semibold">
          Workflow Graph
        </h2>
        <span className="text-[11px] text-aether-muted-dim mono flex items-center gap-1.5">
          <span
            className={`w-1.5 h-1.5 rounded-full ${live ? "bg-aether-green live-dot" : "bg-aether-muted-dim"}`}
            aria-hidden="true"
          />
          {live ? "live data flow" : "paused"}
        </span>
      </div>

      <style>{`@keyframes monitor-dash{to{stroke-dashoffset:-6}}.monitor-flow{animation:monitor-dash 1s linear infinite}@media (prefers-reduced-motion: reduce){.monitor-flow{animation:none}}`}</style>

      <div className="overflow-x-auto">
      <div className="relative h-[420px] sm:h-[520px] min-w-[340px]">
        <svg
          className="absolute inset-0 w-full h-full"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          fill="none"
          aria-hidden="true"
        >
          {WORKFLOW_EDGES.map(([from, to]) => {
            const a = byId.get(from);
            const b = byId.get(to);
            if (!a || !b) return null;
            const active = live && (a.tone === "coral" || a.tone === "green");
            return (
              <line
                key={`${from}-${to}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={active ? "#FF6B35" : "#26263A"}
                strokeWidth={0.4}
                strokeDasharray="1.2 1.8"
                className={active ? "monitor-flow" : undefined}
                opacity={active ? 0.8 : 0.6}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </svg>

        <ul className="contents">
          {nodes.map((node) => {
            const t = TONE[node.tone];
            return (
              <li
                key={node.id}
                className="absolute"
                style={{ left: `${node.x}%`, top: `${node.y}%`, transform: "translate(-50%, -50%)" }}
              >
                <div
                  className={`w-24 glass-raised rounded-2xl border ${t.border} p-3 text-center ${node.pulse ? "live-dot" : ""}`}
                >
                  <div className={`w-9 h-9 mx-auto rounded-xl ${t.iconBg} flex items-center justify-center mb-1.5`}>
                    <i className={`${node.icon} ${t.icon} text-sm`} aria-hidden="true" />
                  </div>
                  <p className="text-[11px] font-semibold">{node.label}</p>
                  <p className={`text-[9px] mono mt-0.5 ${t.text}`}>{node.status}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      </div>
    </section>
  );
}
