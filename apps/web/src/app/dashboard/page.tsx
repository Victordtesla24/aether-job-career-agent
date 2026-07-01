interface StatCard {
  label: string;
  value: string;
  unit?: string;
  icon: string;
  iconColor: string;
  note: string;
  noteColor: string;
}

/**
 * Placeholder stats shown in the Phase 1 dashboard shell. These mirror the
 * approved wireframe (design/screens/dashboard.html) and are replaced with live
 * aggregates once the data layer is wired in a later slice.
 */
const STATS: StatCard[] = [
  {
    label: "Active Applications",
    value: "37",
    icon: "fa-solid fa-paper-plane",
    iconColor: "text-aether-coral",
    note: "+8 this week",
    noteColor: "text-aether-green",
  },
  {
    label: "Interview Rate",
    value: "24",
    unit: "%",
    icon: "fa-solid fa-comments",
    iconColor: "text-aether-indigo",
    note: "+3.2% vs avg",
    noteColor: "text-aether-green",
  },
  {
    label: "Offers",
    value: "3",
    icon: "fa-solid fa-award",
    iconColor: "text-aether-amber",
    note: "2 pending decision",
    noteColor: "text-aether-muted",
  },
  {
    label: "AI Confidence",
    value: "91",
    unit: "%",
    icon: "fa-solid fa-brain",
    iconColor: "text-aether-coral",
    note: "avg match quality",
    noteColor: "text-aether-muted",
  },
];

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-7">
      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        {STATS.map((stat) => (
          <div
            key={stat.label}
            className="glass rounded-2xl border border-white/10 p-5 hover:border-white/20 transition"
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] uppercase tracking-wide text-aether-muted-dim font-medium">
                {stat.label}
              </span>
              <i className={`${stat.icon} ${stat.iconColor} text-sm`} aria-hidden="true" />
            </div>
            <div className="mono text-3xl font-bold">
              {stat.value}
              {stat.unit ? (
                <span className="text-lg text-aether-muted-dim">{stat.unit}</span>
              ) : null}
            </div>
            <div className={`text-xs ${stat.noteColor} mt-2`}>{stat.note}</div>
          </div>
        ))}
      </section>

      <section className="glass rounded-2xl border border-white/10 p-6">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="w-2 h-2 rounded-full bg-aether-green live-dot" />
          <h2 className="text-[15px] font-semibold">Agent Activity</h2>
          <span className="text-[11px] text-aether-muted-dim mono">live</span>
        </div>
        <p className="text-sm text-aether-muted">
          The activity feed, opportunity cards, and approvals panel arrive in the
          next slices. This shell establishes the layout, navigation, and design
          system.
        </p>
      </section>
    </div>
  );
}
