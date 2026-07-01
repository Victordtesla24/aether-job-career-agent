import Link from "next/link";
import { findNavItemByHref } from "@/lib/navigation";

/**
 * Graceful catch-all for dashboard sections whose page has not been built yet
 * (P1-S12). Phase 1 delivers the foundation — the shell, navigation, design
 * system, data model, and backend — while the individual feature workspaces
 * (Jobs, Resume Studio, ...) land in later phases. Rather than letting a nav
 * click fall through to a bare 404, this renders the section title inside the
 * existing shell with an honest "planned for a later phase" panel, so the
 * deployed foundation is coherent to click through end to end.
 */
export default function DashboardSectionPlaceholder({
  params,
}: {
  params: { slug: string[] };
}) {
  const href = `/dashboard/${(params.slug ?? []).join("/")}`;
  const navItem = findNavItemByHref(href);
  const title = navItem?.label ?? "Section not found";
  const icon = navItem?.icon ?? "fa-solid fa-compass";

  return (
    <div className="flex flex-col gap-7">
      <section className="glass rounded-2xl border border-white/10 p-8">
        <div className="flex items-center gap-4 mb-4">
          <div className="w-12 h-12 rounded-2xl bg-aether-coral/12 border border-aether-coral/20 flex items-center justify-center">
            <i className={`${icon} text-aether-coral text-lg`} aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-xl font-semibold">{title}</h2>
            <p className="text-xs text-aether-muted-dim mono mt-0.5">
              {navItem ? "planned workspace" : "unknown route"}
            </p>
          </div>
        </div>

        <p className="text-sm text-aether-muted max-w-2xl leading-relaxed">
          {navItem ? (
            <>
              The <span className="text-white font-medium">{title}</span> workspace is
              part of the Aether roadmap and arrives in a later phase. Phase&nbsp;1
              establishes the foundation this screen builds on — the navigation, the
              shell, the design system, the data model, and the API — all of which are
              in place today.
            </>
          ) : (
            <>
              This route does not map to a known section. Use the sidebar to return to a
              valid workspace.
            </>
          )}
        </p>

        <div className="mt-6 flex items-center gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 text-xs font-medium py-2.5 px-4 rounded-lg bg-aether-coral/12 hover:bg-aether-coral/20 border border-aether-coral/20 text-white transition"
          >
            <i className="fa-solid fa-arrow-left" aria-hidden="true" />
            Back to Dashboard
          </Link>
          <span className="text-[11px] text-aether-muted-dim mono">
            Phase 1 · Foundation
          </span>
        </div>
      </section>
    </div>
  );
}
