import Link from "next/link";

/**
 * Graceful catch-all for unknown dashboard routes (P1-S12). Every nav section
 * now has a dedicated workspace page, so this only serves routes that map to
 * no known section — rendering an in-shell "unknown route" panel instead of a
 * bare 404.
 */
export default function DashboardSectionNotFound({
  params,
}: {
  params: { slug: string[] };
}) {
  const href = `/dashboard/${(params.slug ?? []).join("/")}`;

  return (
    <div className="flex flex-col gap-7">
      <section className="glass rounded-2xl border border-white/10 p-8">
        <div className="flex items-center gap-4 mb-4">
          <div className="w-12 h-12 rounded-2xl bg-aether-coral/12 border border-aether-coral/20 flex items-center justify-center">
            <i className="fa-solid fa-compass text-aether-coral text-lg" aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-xl font-semibold">Section not found</h2>
            <p className="text-xs text-aether-muted-dim mono mt-0.5">unknown route</p>
          </div>
        </div>

        <p className="text-sm text-aether-muted max-w-2xl leading-relaxed">
          <span className="mono text-white">{href}</span> does not map to a known section.
          Use the sidebar to return to a valid workspace.
        </p>

        <div className="mt-6 flex items-center gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 text-xs font-medium py-2.5 px-4 rounded-lg bg-aether-coral/12 hover:bg-aether-coral/20 border border-aether-coral/20 text-white transition"
          >
            <i className="fa-solid fa-arrow-left" aria-hidden="true" />
            Back to Dashboard
          </Link>
        </div>
      </section>
    </div>
  );
}
