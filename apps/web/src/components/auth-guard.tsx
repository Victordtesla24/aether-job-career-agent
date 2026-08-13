"use client";

/**
 * Client-side session gate for the /dashboard shell (SC-AUTH-03).
 *
 * The session JWT lives in localStorage (written by /login), so the server
 * cannot see it and the check happens on mount: no stored token → redirect to
 * /login. Children stay unrendered until the check passes so an
 * unauthenticated visitor never sees a flash of the workspace chrome.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const TOKEN_STORAGE_KEY = "aether_token";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    if (window.localStorage.getItem(TOKEN_STORAGE_KEY)) {
      setAuthed(true);
    } else {
      const path = window.location.pathname;
      const search = window.location.search;
      // C-06 (QA-v2): an unauthenticated visitor who lands on the app root
      // (`/` redirects to `/dashboard` via next.config) previously hit a bare
      // /login form with zero information about the product. Send that root
      // landing to the public /pricing page instead — it is the real public
      // landing page (tiers, feature copy, a "Sign in" link). This only fires
      // for the exact /dashboard root with no deep path or query: a genuine
      // deep-link (e.g. a bookmarked /dashboard/jobs) still goes to /login so
      // the ?next round-trip returns the user where they intended to go.
      if (path === "/dashboard" && search === "") {
        router.replace("/pricing");
        return;
      }
      // Preserve the originally-requested destination so /login can return the
      // visitor there instead of dropping them on bare /dashboard
      // (MV-login-002). safeNextPath re-validates it on the login side, so an
      // attacker-crafted value here can never become an open redirect.
      const intended = path + search;
      router.replace(`/login?next=${encodeURIComponent(intended)}`);
    }
  }, [router]);

  if (!authed) return null;
  return <>{children}</>;
}
