"use client";

/**
 * U-STORY-3a — a shareable on/off view state held in the query string
 * (`?links=1`), built on exactly the pattern `useUrlTab` already proved.
 *
 * Deliberately NOT `useSearchParams()`/`useRouter()`, for the same reasons
 * spelled out there: reading `window.location` and pushing with the History
 * API keeps this a pure client concern — no server round-trip, no Suspense
 * boundary for a static export, and no router provider needed by the unit
 * tests that render these components bare.
 *
 * WHY IT MATTERS HERE. "Show me how story extraction reaches my cover letter"
 * is a thing one person wants to send to another. With the flag in the URL the
 * link they paste opens on the same view; without it, it opens on the default
 * and the point is lost.
 *
 * The flag is only ever WRITTEN as `?links=1`, and REMOVED when turned off, so
 * the URL never accumulates `links=0` noise. Back/Forward are honoured through
 * `popstate`, and an unrecognised value degrades to OFF without rewriting
 * anyone's address bar.
 */
import { useCallback, useEffect, useState } from "react";

/** Values that mean ON. Anything else (absent, "0", "false", junk) is OFF. */
const TRUTHY = new Set(["1", "true", "yes", "on"]);

function readFlag(param: string): boolean {
  if (typeof window === "undefined") return false;
  const raw = new URLSearchParams(window.location.search).get(param);
  return raw !== null && TRUTHY.has(raw.toLowerCase());
}

export function useUrlFlag(param: string): [boolean, (next: boolean) => void] {
  // `false` on the server AND on the first client render, so hydration is
  // deterministic; the URL's value is adopted in an effect immediately after.
  const [on, setOn] = useState(false);

  useEffect(() => {
    setOn(readFlag(param));
    const onPop = () => setOn(readFlag(param));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [param]);

  const set = useCallback(
    (next: boolean) => {
      setOn(next);
      if (typeof window === "undefined") return;
      const url = new URL(window.location.href);
      if (next) url.searchParams.set(param, "1");
      else url.searchParams.delete(param);
      window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    },
    [param],
  );

  return [on, set];
}
