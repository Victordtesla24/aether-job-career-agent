"use client";

/**
 * Root route (`/`) — single-hop session-aware landing.
 *
 * The session JWT lives in localStorage (written by /login and /signup), so
 * the server cannot see it. Previously `/` was config-redirected to /dashboard
 * and the client AuthGuard then bounced anonymous visitors on to /pricing —
 * two hops and a flash of the dashboard shell for logged-out users. This page
 * reads the token once on mount and routes directly:
 *   - authenticated → /dashboard
 *   - anonymous     → /pricing (the real public landing page)
 * Nothing but a neutral splash renders in between, so there is no flicker of
 * the wrong destination.
 */
import { useRouter } from "next/navigation";
import { useEffect } from "react";

const TOKEN_STORAGE_KEY = "aether_token";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    const authed = Boolean(window.localStorage.getItem(TOKEN_STORAGE_KEY));
    router.replace(authed ? "/dashboard" : "/pricing");
  }, [router]);

  return (
    <main className="min-h-screen flex items-center justify-center bg-aether-bg px-4">
      <p className="text-sm text-aether-muted">Loading…</p>
    </main>
  );
}
