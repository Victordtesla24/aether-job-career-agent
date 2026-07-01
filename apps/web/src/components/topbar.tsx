/**
 * Dashboard top bar: greeting, global search, notifications, and the user chip.
 * Copy is static placeholder content for the Phase 1 shell; live data is wired
 * in later slices.
 */
export function Topbar({
  title = "Good morning, Vikram",
  subtitle = "Your agents worked through the night",
}: {
  title?: string;
  subtitle?: string;
}) {
  return (
    <header className="h-16 shrink-0 border-b border-white/10 glass flex items-center justify-between px-8">
      <div>
        <h1 className="text-[15px] font-semibold">{title}</h1>
        <p className="text-xs text-aether-muted-dim mono">{subtitle}</p>
      </div>
      <div className="flex items-center gap-3">
        <div className="relative w-72 hidden md:block">
          <i className="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-aether-muted-dim text-sm" />
          <input
            type="text"
            placeholder="Search jobs, applications, agents..."
            aria-label="Search"
            className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
          />
        </div>
        <button
          type="button"
          aria-label="Notifications"
          className="relative w-10 h-10 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition flex items-center justify-center"
        >
          <i className="fa-regular fa-bell text-aether-muted" />
          <span className="absolute top-2 right-2.5 w-2 h-2 rounded-full bg-aether-coral" />
        </button>
        <div className="flex items-center gap-2.5 pl-3 border-l border-white/10">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-aether-indigo to-aether-violet flex items-center justify-center text-sm font-semibold">
            VD
          </div>
          <div className="leading-tight">
            <div className="text-[13px] font-medium">Vikram D.</div>
            <div className="text-[11px] text-aether-muted-dim">Pro plan</div>
          </div>
        </div>
      </div>
    </header>
  );
}
