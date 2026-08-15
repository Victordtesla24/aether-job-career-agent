"use client";

/**
 * Shared route-level error boundary UI (C-03, QA-v2).
 *
 * Next.js App Router renders the nearest `error.tsx` when a route segment
 * throws during render. Before this existed, a runtime error in a dashboard
 * workspace (e.g. a data-shape mismatch, or a chunk that failed to load from a
 * stale deploy) unmounted the whole subtree and left a BLANK page with no
 * chrome and no message — exactly the "completely blank" failure the QA v2
 * report logged for Applications, Resume Studio and Email Center. This
 * component turns that silent blank into an honest, recoverable error card:
 * the section name, a plain-language message, a "Try again" button wired to
 * the boundary's `reset()`, and a link back to the dashboard so the user is
 * never stranded.
 */
import Link from "next/link";
import { useEffect } from "react";

export function RouteError({
  section,
  error,
  reset,
}: {
  section: string;
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface to the browser console for support/debugging; never swallowed.
    // eslint-disable-next-line no-console
    console.error(`[${section}] route error:`, error);
  }, [error, section]);

  return (
    <div
      role="alert"
      data-testid="route-error"
      className="mx-auto mt-6 max-w-lg rounded-[14px] border border-[#B9544B]/40 bg-[#B9544B]/10 p-6 text-center"
    >
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-aether-coral/15">
        <i className="fa-solid fa-triangle-exclamation text-lg text-aether-coral" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold text-aether-text">
        {section} couldn&rsquo;t load
      </h2>
      <p className="mt-2 text-sm text-aether-muted">
        Something went wrong while loading this workspace. This is usually
        temporary — try again, and if it keeps happening reload the page.
      </p>
      {error?.digest ? (
        <p className="mt-2 font-mono text-[10px] text-aether-muted-dim">
          ref: {error.digest}
        </p>
      ) : null}
      <div className="mt-5 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => reset()}
          data-testid="route-error-retry"
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-[#0A0A0A] transition hover:bg-aether-coral-accent"
        >
          <i className="fa-solid fa-rotate-right mr-2" aria-hidden="true" />
          Try again
        </button>
        <Link
          href="/dashboard"
          className="rounded-xl border border-white/15 px-4 py-2 text-sm font-semibold text-aether-muted transition hover:border-white/30 hover:text-white"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}

/**
 * Shared route-level loading skeleton (C-03). Rendered by a segment's
 * `loading.tsx` while its Suspense boundary resolves, so a heavy workspace
 * shows structured placeholders instead of a blank pane or a "0 discovered"
 * flash (also addresses L-01 / M-10).
 */
export function RouteSkeleton({ section }: { section: string }) {
  return (
    <div data-testid="route-skeleton" aria-busy="true" aria-live="polite" className="space-y-5">
      <span className="sr-only">Loading {section}…</span>
      <div className="h-8 w-56 animate-pulse rounded-lg bg-white/5" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-[14px] border border-white/10 bg-white/5" />
        ))}
      </div>
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-xl border border-white/10 bg-white/5" />
        ))}
      </div>
    </div>
  );
}
