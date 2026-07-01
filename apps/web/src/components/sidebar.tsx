import Link from "next/link";
import { NAV_ITEMS } from "@/lib/navigation";

/**
 * Primary application sidebar. It renders straight from the NAV_ITEMS contract
 * (see src/lib/navigation.ts) so the ordering asserted by the navigation
 * contract test is exactly what ships. The `activeHref` prop highlights the
 * current section; matching is prefix-based for nested routes.
 */
export function Sidebar({ activeHref }: { activeHref: string }) {
  return (
    <aside className="w-[248px] shrink-0 border-r border-white/10 glass flex flex-col px-4 py-6">
      <div className="flex items-center gap-3 px-2 mb-8">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-aether-coral to-aether-amber flex items-center justify-center shadow-lg shadow-aether-coral/30">
          <i className="fa-solid fa-bolt text-white text-sm" />
        </div>
        <div>
          <div className="font-bold text-[15px] leading-none">Aether</div>
          <div className="text-[11px] text-aether-muted-dim mt-1">Career Agent</div>
        </div>
      </div>

      <nav aria-label="Primary" className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/dashboard"
              ? activeHref === "/dashboard"
              : activeHref.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={
                isActive
                  ? "flex items-center gap-3 px-3 py-2.5 rounded-xl bg-aether-coral/12 text-white border border-aether-coral/20 text-sm font-medium"
                  : "flex items-center gap-3 px-3 py-2.5 rounded-xl text-aether-muted hover:bg-white/5 hover:text-white transition text-sm"
              }
            >
              <i
                className={`${item.icon} w-4${isActive ? " text-aether-coral" : ""}`}
                aria-hidden="true"
              />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto glass-raised rounded-2xl p-4 border border-white/10">
        <div className="flex items-center gap-2 mb-2">
          <span className="w-2 h-2 rounded-full bg-aether-green live-dot" />
          <span className="text-xs font-medium text-aether-green">Agents Active</span>
        </div>
        <p className="text-[11px] text-aether-muted-dim leading-relaxed">
          4 agents running · 12 tasks in queue
        </p>
        <button
          type="button"
          className="mt-3 w-full text-xs font-medium py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition"
        >
          Manage Agents
        </button>
      </div>
    </aside>
  );
}
