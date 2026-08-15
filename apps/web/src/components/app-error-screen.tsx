"use client";

/**
 * Shared root-level error-boundary UI (O-5, S-FIX slice C). Rendered by both
 * app/error.tsx (a render error anywhere outside a route segment that has
 * its own error.tsx, e.g. the public marketing/auth pages) and
 * app/global-error.tsx (a throw in the root layout itself, which unmounts
 * the whole tree). Before this, no root-level boundary existed at all, so
 * either case fell through to Next.js's stock, unbranded error page.
 *
 * Mirrors the existing dashboard boundary (components/route-error.tsx):
 * honest copy, a working retry, and a way out. Unlike RouteError this
 * component is reachable from public/unauthenticated routes too, so "back to
 * dashboard" would be wrong — it links to `/` instead. It is also reachable
 * from the very layout that would normally supply request-time config, so it
 * cannot safely call `getOperatorLegalConfig()` (server-only, env-backed);
 * rather than baking a support address into the client bundle at build time,
 * the support link points at the Privacy Policy's own Contact section, which
 * resolves the live AETHER_SUPPORT_EMAIL at request time.
 */
import Link from "next/link";
import { useEffect } from "react";

export function AppErrorScreen({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface to the browser console for support/debugging; never swallowed.
    // eslint-disable-next-line no-console
    console.error("[root] unhandled error:", error);
  }, [error]);

  return (
    <div
      role="alert"
      data-testid="app-error-screen"
      className="min-h-screen flex items-center justify-center bg-aether-bg text-aether-text px-4"
    >
      <div className="w-full max-w-md text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-aether-coral/15">
          <i className="fa-solid fa-triangle-exclamation text-lg text-aether-coral" aria-hidden="true" />
        </div>
        <h1 className="text-xl font-bold tracking-tight">Something went wrong</h1>
        <p className="mt-2 text-sm text-aether-muted leading-relaxed">
          An unexpected error occurred. This is usually temporary — try again, and contact us
          if it keeps happening.
        </p>
        {error?.digest ? (
          <p className="mt-2 font-mono text-[10px] text-aether-muted-dim">ref: {error.digest}</p>
        ) : null}
        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => reset()}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-[#0A0A0A] transition hover:bg-aether-coral-accent"
          >
            <i className="fa-solid fa-rotate-right mr-2" aria-hidden="true" />
            Try again
          </button>
          <Link
            href="/"
            className="rounded-xl border border-white/15 px-4 py-2 text-sm font-semibold text-aether-muted transition hover:border-white/30 hover:text-white"
          >
            Go home
          </Link>
        </div>
        <p className="mt-6 text-xs text-aether-muted-dim">
          Need help?{" "}
          <Link href="/privacy-policy" className="text-aether-coral hover:underline">
            Contact support
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
