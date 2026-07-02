import DashboardStats from "../../components/dashboard/DashboardStats";

/**
 * Dashboard home — live stat cards sourced from GET /analytics/funnel
 * (see components/dashboard/DashboardStats). No hardcoded placeholder numbers.
 */
export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-7">
      <DashboardStats />

      <section className="glass rounded-2xl border border-white/10 p-6">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="w-2 h-2 rounded-full bg-aether-green live-dot" />
          <h2 className="text-[15px] font-semibold">Agent Activity</h2>
          <span className="text-[11px] text-aether-muted-dim mono">live</span>
        </div>
        <p className="text-sm text-aether-muted">
          Head to the Agents workspace to trigger runs, review recent activity,
          and launch the full discovery → tailoring pipeline. Anything that
          leaves the system waits for your approval first.
        </p>
      </section>
    </div>
  );
}
