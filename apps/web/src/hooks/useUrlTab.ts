"use client";

/**
 * S-UI §4.1 — a linkable, back-button-correct tab selection held in the URL
 * query string (`?tab=`).
 *
 * Deliberately NOT `useSearchParams()`/`useRouter()`: reading the location
 * directly and pushing with the History API keeps the tab state a pure
 * client concern (no server round-trip, no Suspense boundary requirement for
 * a static export, and no router provider needed by the page's existing unit
 * tests, which render the page component bare). Next 14 supports native
 * `history.pushState` for exactly this case.
 *
 * `popstate` is observed so Back/Forward move between tabs, and an unknown or
 * absent `?tab=` value falls back to `fallback` WITHOUT rewriting the URL —
 * a bad link degrades to the default view rather than 404-ing or silently
 * mutating someone's address bar.
 */
import { useCallback, useEffect, useState } from "react";

function readTab<T extends string>(allowed: ReadonlyArray<T>, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  const raw = new URLSearchParams(window.location.search).get("tab");
  const match = allowed.find((t) => t === raw);
  return match ?? fallback;
}

export function useUrlTab<T extends string>(
  allowed: ReadonlyArray<T>,
  fallback: T,
): [T, (next: T) => void] {
  // Start on `fallback` for a deterministic first render (SSR and client
  // agree), then adopt the URL's value in an effect.
  const [tab, setTab] = useState<T>(fallback);

  useEffect(() => {
    setTab(readTab(allowed, fallback));
    const onPop = () => setTab(readTab(allowed, fallback));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // `allowed` MUST be a stable (module-level) array at the call site — it is
    // a dependency here, so an inline literal would re-subscribe every render.
  }, [allowed, fallback]);

  const select = useCallback((next: T) => {
    setTab(next);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }, []);

  return [tab, select];
}
