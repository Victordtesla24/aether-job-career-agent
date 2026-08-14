/**
 * Near-miss resolution for the dashboard catch-all (`/dashboard/[...slug]`).
 *
 * WHY THIS EXISTS — the Story Bank "Section not found" defect.
 * Measured on production 2026-08-14 (evidence:
 * `uat/reports/evidence/market-perf/s-ui/b3/before/before-notes.json` +
 * `before-probe-dashboard-story-bank.png`):
 *
 *   /dashboard/stories      -> the real Story Bank      (h1 "Achievement & Narrative Library")
 *   /dashboard/story-bank   -> the catch-all            ("Section not found")
 *   /story-bank             -> Next's own 404           ("Page not found")
 *
 * The sidebar's own href is `/dashboard/stories` and click-through works, so
 * the report was produced by visiting the WIREFRAME name (`story-bank`) rather
 * than the shipped route — the same wrong name still baked into the stale
 * Phase-0 capture harness (`e2e/capture-authenticated-baselines.spec.ts`).
 * The routing is correct; the DEAD END is the defect. A user who lands on the
 * old name is told the section does not exist, next to a sidebar in which it
 * plainly does.
 *
 * So the catch-all now names the section it almost certainly meant. It
 * SUGGESTS — it never redirects. A silent redirect would be exactly the
 * "silent fallback" the honesty rules forbid: the user would have no way to
 * learn the URL they used is not a real one.
 *
 * Pure data. No React, no fetch, no new contract: it reads the existing
 * `NAV_ITEMS` and nothing else.
 */
import { NAV_ITEMS } from "./navigation";

export interface NavSuggestion {
  label: string;
  href: string;
  /** Which rule matched — surfaced in tests, not in copy. */
  reason: "label-slug" | "href-token" | "prefix";
}

/** "Story Bank" -> "story-bank"; "/dashboard/cover-letters" -> "cover-letters". */
function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** The last path segment of a nav href: "/dashboard/stories" -> "stories". */
function hrefToken(href: string): string {
  const parts = href.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

/**
 * The nav section an unknown `/dashboard/<slug>` most likely meant, or `null`
 * when nothing is close enough to name honestly.
 *
 * Matching is deliberately conservative — three exact-ish rules, no fuzzy
 * distance metric. A wrong suggestion is worse than none: it would send a
 * paying subscriber to a screen they did not ask for and quietly teach them a
 * URL that still does not exist.
 *
 *  1. `label-slug` — the slug IS a nav label, slugified ("story-bank" ->
 *     "Story Bank"). This is the wireframe-name case the defect came from.
 *  2. `href-token`  — the slug is a nav href's own last segment with the
 *     separators written differently ("cover_letters" -> "cover-letters").
 *  3. `prefix`      — the slug is a strict, non-trivial prefix of either of
 *     the above and resolves to exactly ONE section ("interview" ->
 *     "Interview Center"). Ambiguous prefixes yield nothing.
 */
export function suggestNavItem(slug: string): NavSuggestion | null {
  const wanted = slugify(slug);
  if (!wanted) return null;

  for (const item of NAV_ITEMS) {
    if (slugify(item.label) === wanted) {
      return { label: item.label, href: item.href, reason: "label-slug" };
    }
  }
  for (const item of NAV_ITEMS) {
    if (slugify(hrefToken(item.href)) === wanted) {
      return { label: item.label, href: item.href, reason: "href-token" };
    }
  }

  if (wanted.length < 4) return null;
  const prefixed = NAV_ITEMS.filter(
    (item) =>
      slugify(item.label).startsWith(wanted) || slugify(hrefToken(item.href)).startsWith(wanted),
  );
  if (prefixed.length === 1) {
    return { label: prefixed[0].label, href: prefixed[0].href, reason: "prefix" };
  }
  return null;
}

/**
 * The full `/dashboard/...` path a catch-all render was asked for, built the
 * same way the page already builds it. Exported so the page and its tests
 * agree on the string that is shown to the user.
 */
export function joinSlug(slug: readonly string[] | undefined): string {
  return `/dashboard/${(slug ?? []).join("/")}`;
}
