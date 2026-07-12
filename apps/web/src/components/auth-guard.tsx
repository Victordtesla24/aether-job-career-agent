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
      router.replace("/login");
    }
  }, [router]);

  if (!authed) return null;
  return <>{children}</>;
}
