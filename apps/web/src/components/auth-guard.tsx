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
      // Preserve the originally-requested destination so /login can return the
      // visitor there instead of dropping them on bare /dashboard
      // (MV-login-002). safeNextPath re-validates it on the login side, so an
      // attacker-crafted value here can never become an open redirect.
      const intended = window.location.pathname + window.location.search;
      router.replace(`/login?next=${encodeURIComponent(intended)}`);
    }
  }, [router]);

  if (!authed) return null;
  return <>{children}</>;
}
