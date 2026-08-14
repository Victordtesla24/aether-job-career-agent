import Link from "next/link";

import { joinSlug, suggestNavItem } from "../../../lib/navigation-suggest";

/**
 * Graceful catch-all for unknown dashboard routes (P1-S12). Every nav section
 * now has a dedicated workspace page, so this only serves routes that map to
 * no known section — rendering an in-shell "unknown route" panel instead of a
 * bare 404.
 *
 * S-UI B3 — the Story Bank dead end.
 * Production evidence (b3/before/before-notes.json, 2026-08-14):
 * `/dashboard/stories` renders the real Story Bank and the sidebar links to
 * it, but `/dashboard/story-bank` — the WIREFRAME name, still hard-coded in
 * the stale Phase-0 capture harness — landed here and told the user the
 * section does not exist while it was visible in the sidebar. That is where
 * the reported "Story Bank shows Section not found" came from: not a routing
 * or data bug, a dead end on a near-miss URL.
 *
 * This panel now NAMES the section a near-miss almost certainly meant
 * (`lib/navigation-suggest.ts`). It suggests; it never redirects — a silent
 * redirect would hide the fact that the URL used is not a real one, which is
 * precisely the silent fallback the honesty rules forbid. The heading, the
 * "unknown route" line and the requested path all stay exactly as they were.
 */
export default function DashboardSectionNotFound({
  params,
}: {
  params: { slug: string[] };
}) {
  const href = joinSlug(params.slug);
  const slug = (params.slug ?? []).join("/");
  const suggestion = suggestNavItem(slug);

  return (
    <div className="flex flex-col gap-7">
      <section className="elev-1 rounded-2xl p-8">
        <div className="mb-4 flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-aether-coral/20 bg-aether-coral/[0.12]">
            <i className="fa-solid fa-compass text-lg text-aether-coral" aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-xl font-semibold tracking-[-0.015em]">Section not found</h2>
            <p className="mono mt-0.5 text-xs text-aether-muted-dim">unknown route</p>
          </div>
        </div>

        <p className="max-w-2xl text-sm leading-relaxed text-aether-muted">
          <span className="mono text-aether-text">{href}</span> does not map to a known section.
          Use the sidebar to return to a valid workspace.
        </p>

        {suggestion ? (
          <div
            className="mt-5 max-w-2xl rounded-xl border border-aether-coral/25 bg-aether-coral/[0.07] p-4"
            data-testid="section-suggestion"
          >
            <p className="text-sm text-aether-text">
              Did you mean{" "}
              <Link
                href={suggestion.href}
                className="font-semibold text-aether-coral underline underline-offset-2"
                data-testid="section-suggestion-link"
              >
                {suggestion.label}
              </Link>
              ?
            </p>
            <p className="mt-1 text-xs text-aether-muted-dim">
              That section lives at <span className="mono">{suggestion.href}</span> — this address
              is an older name for it and was never a route.
            </p>
          </div>
        ) : null}

        <div className="mt-6 flex items-center gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-lg border border-aether-coral/20 bg-aether-coral/[0.12] px-4 py-2.5 text-xs font-medium text-aether-text transition-colors duration-[--dur-fast] hover:bg-aether-coral/20"
          >
            <i className="fa-solid fa-arrow-left" aria-hidden="true" />
            Back to Dashboard
          </Link>
        </div>
      </section>
    </div>
  );
}
