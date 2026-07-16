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
    fetchMe()
      .then((me) => {
        if (cancelled) return;
        if (me.isAdmin) {
          setState("allowed");
        } else {
          setState("denied");
          router.replace("/dashboard");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setState("denied");
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        } else {
          router.replace("/dashboard");
        }
      });
    return () => {
      cancelled = true;
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
