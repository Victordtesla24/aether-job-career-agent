"use client";

/**
 * Client-side admin gate for the /admin shell (GAP-P6-ADMIN-001, GATE-17).
 *
 * Two-stage: (1) no session token → /login (mirrors AuthGuard); (2) a session
 * that is NOT an admin → /dashboard. The backend enforces the real gate (every
 * /api/admin/* route depends on `AdminUser` and 403s a non-admin) — this guard
 * only prevents a non-admin from seeing admin chrome flash. Children stay
 * unrendered until `isAdmin` is confirmed.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "../../lib/api/client";
import { fetchMe } from "../../lib/api/admin";

const TOKEN_STORAGE_KEY = "aether_token";

type GateState = "checking" | "allowed" | "denied";

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<GateState>("checking");

  useEffect(() => {
    let cancelled = false;
    if (!window.localStorage.getItem(TOKEN_STORAGE_KEY)) {
      router.replace("/login");
      return;
    }
    // C-04 (QA-v2): the admin health page was observed permanently stuck on
    // "Verifying admin access..." — if fetchMe() never settles (a hung
    // request, a chunk that failed to load, a flaky network) the gate stayed
    // in "checking" forever and the page never rendered. A token holder has
    // already passed the localStorage check above and the BACKEND is the real
    // authority (every /api/admin/* route independently enforces AdminUser and
    // 403s a non-admin), so falling THROUGH to render the admin chrome after a
    // grace period is safe: a non-admin who slips past this client hint simply
    // sees empty/forbidden data from the API, never privileged data. The
    // timeout only ever fires if the /auth/me check hasn't resolved in time.
    const fallback = setTimeout(() => {
      if (!cancelled) {
        setState((prev) => (prev === "checking" ? "allowed" : prev));
      }
    }, 4000);
    fetchMe()
      .then((me) => {
        if (cancelled) return;
        clearTimeout(fallback);
        if (me.isAdmin) {
          setState("allowed");
        } else {
          setState("denied");
          router.replace("/dashboard");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        clearTimeout(fallback);
        // A definitive 401 means the session is gone — bounce to /login. Any
        // OTHER failure (network/transient) is NOT proof the user is a
        // non-admin, so we no longer eagerly redirect to /dashboard on it;
        // the timeout above will fall through to render and let the API be
        // the authority, matching the "never strand a real admin" goal.
        if (err instanceof ApiError && err.status === 401) {
          setState("denied");
          router.replace("/login");
        } else if (err instanceof ApiError && err.status === 403) {
          setState("denied");
          router.replace("/dashboard");
        } else {
          setState((prev) => (prev === "checking" ? "allowed" : prev));
        }
      });
    return () => {
      cancelled = true;
      clearTimeout(fallback);
    };
  }, [router]);

  if (state !== "allowed") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-aether-bg text-aether-muted">
        <p className="text-sm">
          {state === "checking" ? "Verifying admin access…" : "Redirecting…"}
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
