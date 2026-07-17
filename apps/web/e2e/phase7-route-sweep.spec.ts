import { test, expect, request as apiRequest } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Phase-7 route sweep (PROBE-P7-12).
 *
 * Visits every real, authenticated dashboard/top-level route once, capturing
 * console errors, same-origin/cross-origin HTTP errors (>=400), and a
 * full-page screenshot per route, then writes one aggregate JSON artifact.
 * This is a probe/evidence spec, not a functional-behavior spec — assertions
 * exist so `playwright test` reports a clear pass/fail per route, but the
 * qa agent is the one who adjudicates the JSON artifact, per the
 * record-don't-fail policy below.
 *
 * ROUTE DISCOVERY (2026-07-17, from `find apps/web/src/app -iname page.tsx`)
 * [VERIFIED-WITH-SOURCE]: 25 total page.tsx files exist under
 * apps/web/src/app. The prompt's "15 dashboard routes" figure does not match
 * the actual tree, so this sweep uses the real enumeration below instead.
 *
 * Dashboard subtree (14 routes — every apps/web/src/app/dashboard/*\/page.tsx
 * plus the dashboard index itself):
 *   /dashboard, /dashboard/agents, /dashboard/analytics,
 *   /dashboard/applications, /dashboard/approvals, /dashboard/cover-letters,
 *   /dashboard/email, /dashboard/interviews, /dashboard/jobs,
 *   /dashboard/networking, /dashboard/offers, /dashboard/resume,
 *   /dashboard/settings, /dashboard/stories
 *
 * Top-level user-facing routes (6 — every apps/web/src/app/*\/page.tsx one
 * level deep, excluding dashboard/* itself, per the prompt's "plus any
 * top-level user-facing routes like /pricing" instruction):
 *   /admin, /login, /pricing, /privacy-policy, /signup, /terms
 *
 * Total swept: 20 routes.
 *
 * Explicitly EXCLUDED (with reasons):
 *   - /dashboard/[...slug] — a catch-all fallback, not a concrete route;
 *     already covered by the "unknown routes get a graceful panel" case in
 *     e2e/dashboard.spec.ts.
 *   - /admin/audit-log, /admin/health, /admin/settings, /admin/spend,
 *     /admin/users — nested under admin/*, which the prompt's route-list
 *     instruction only calls out one level deep ("dashboard/* plus
 *     top-level routes"); admin's own sub-surface is a distinct RBAC-gated
 *     area better covered by an admin-specific probe.
 *   - /admin/users/[id] — dynamic route, no fixture id available.
 *
 * AUTH: API login (POST {BASE_URL}/api/auth/login, same contract as
 * apps/web/src/lib/api/auth.ts's `login()`) followed by injecting the
 * returned access_token into localStorage under the "aether_token" key via
 * context.addInitScript — the exact pattern already proven in
 * uat/phase6_console_sweep.py and asserted against in e2e/login.spec.ts
 * ("JWT stored under the shared aether_token key"). This spec does NOT use
 * the repo's existing "setup" Playwright project / e2e/.auth/user.json
 * storageState (see playwright.config.ts) because that project (a) drives a
 * REAL UI login against the LOCAL dev baseURL (http://127.0.0.1:3000), not
 * BASE_URL, and (b) this file must stay self-contained without editing
 * playwright.config.ts. `test.use({ storageState: {...} })` below overrides
 * any project-level storageState so a missing e2e/.auth/user.json (e.g. a
 * fresh checkout, or a run with --no-deps) can never break this spec.
 *
 * CREDENTIALS: [ASSUMED-PENDING-PROBE] — AETHER_E2E_EMAIL/AETHER_E2E_PASSWORD
 * default to "admin"/"admin123" per the parent prompt's stated canonical
 * test account; this default has NOT been independently verified against
 * the seeded DB by this fixer (test-only change, no DB access taken). Set
 * the env vars explicitly for a real run instead of relying on the default.
 *
 * SINGLE-TEST DESIGN: all 20 routes are swept inside one `test()` with a
 * sequential loop (not one `test()` per route). playwright.config.ts sets
 * `fullyParallel: true`, which lets Playwright's test runner schedule
 * separate `test()` calls from the same file onto DIFFERENT worker
 * processes — each worker is a separate Node process with its own module
 * state, so a module-level `results` array filled by N parallel `test()`
 * calls and flushed once in `test.afterAll` (the pattern used by
 * e2e/mobile-regression.spec.ts) is not guaranteed to contain every route's
 * result when workers > 1. Looping inside a single test keeps the whole
 * sweep single-process, so the JSON artifact is always complete regardless
 * of --workers. `expect.soft()` is used per route so one route's failure
 * never skips the remaining routes.
 */

test.use({ storageState: { cookies: [], origins: [] } });

const BASE_URL = (process.env.BASE_URL || "https://5cb5f0620.abacusai.cloud").replace(/\/+$/, "");
const BASE_HOST = new URL(BASE_URL).host;
const API_BASE = `${BASE_URL}/api`;
const TOKEN_STORAGE_KEY = "aether_token";

const E2E_EMAIL = process.env.AETHER_E2E_EMAIL || "admin";
const E2E_PASSWORD = process.env.AETHER_E2E_PASSWORD || "admin123";

const EVIDENCE_ROOT = path.resolve(process.cwd(), "../../uat/reports/evidence/phase7");
const SCREENSHOT_DIR = path.join(EVIDENCE_ROOT, "playwright-route-sweep");
const SUMMARY_PATH = path.join(EVIDENCE_ROOT, "probe-p7-12-route-results.json");

// No third-party analytics vendor is wired into apps/web today (grepped
// package.json + src for google-analytics/segment/mixpanel/sentry/etc. —
// zero hits), so there is nothing to ignore yet. Kept as an explicit,
// documented allowlist so a future analytics integration doesn't require
// touching the sweep loop itself, only this list.
const IGNORED_HOST_SUBSTRINGS: string[] = [];

const DASHBOARD_ROUTES = [
  "/dashboard",
  "/dashboard/agents",
  "/dashboard/analytics",
  "/dashboard/applications",
  "/dashboard/approvals",
  "/dashboard/cover-letters",
  "/dashboard/email",
  "/dashboard/interviews",
  "/dashboard/jobs",
  "/dashboard/networking",
  "/dashboard/offers",
  "/dashboard/resume",
  "/dashboard/settings",
  "/dashboard/stories",
];

const TOP_LEVEL_ROUTES = ["/admin", "/login", "/pricing", "/privacy-policy", "/signup", "/terms"];

const ROUTES = [...DASHBOARD_ROUTES, ...TOP_LEVEL_ROUTES];

interface RouteResult {
  route: string;
  consoleErrors: string[];
  httpErrors: { url: string; status: number }[];
  screenshot: string;
}

function slug(route: string): string {
  return route.replace(/^\//, "").replace(/\//g, "-") || "root";
}

async function getAuthToken(): Promise<string> {
  const ctx = await apiRequest.newContext();
  try {
    const res = await ctx.post(`${API_BASE}/auth/login`, {
      data: { email: E2E_EMAIL, password: E2E_PASSWORD },
    });
    if (!res.ok()) {
      throw new Error(
        `route-sweep login failed: HTTP ${res.status()} for "${E2E_EMAIL}" against ` +
          `${API_BASE}/auth/login — set AETHER_E2E_EMAIL/AETHER_E2E_PASSWORD to a real account.`,
      );
    }
    const body = (await res.json()) as { access_token?: string };
    if (!body.access_token) {
      throw new Error("route-sweep login response missing access_token");
    }
    return body.access_token;
  } finally {
    await ctx.dispose();
  }
}

test.describe("Phase-7 route sweep (PROBE-P7-12)", () => {
  test("sweeps every dashboard + top-level route for console/HTTP errors and screenshots", async ({
    context,
  }) => {
    // 20 routes x up to 45s network-idle wait each comfortably exceeds the
    // framework's default 30s test timeout.
    test.setTimeout(20 * 60 * 1000);

    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

    const token = await getAuthToken();
    await context.addInitScript(
      ({ key, value }) => window.localStorage.setItem(key, value),
      { key: TOKEN_STORAGE_KEY, value: token },
    );

    const results: RouteResult[] = [];

    try {
      for (const route of ROUTES) {
        const page = await context.newPage();
        const consoleErrors: string[] = [];
        const httpErrors: { url: string; status: number }[] = [];

        page.on("console", (msg) => {
          if (msg.type() === "error") consoleErrors.push(msg.text());
        });
        // Uncaught exceptions are folded into consoleErrors too: they are a
        // strictly more severe signal of a broken route than a console.error
        // call, and the fail condition below ("any console error") is meant
        // to catch exactly this class of visible breakage.
        page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
        page.on("response", (resp) => {
          const status = resp.status();
          if (status < 400) return;
          const url = resp.url();
          if (IGNORED_HOST_SUBSTRINGS.some((h) => url.includes(h))) return;
          httpErrors.push({ url, status });
        });

        let navError: string | null = null;
        try {
          await page.goto(`${BASE_URL}${route}`, { waitUntil: "networkidle", timeout: 45_000 });
          await page.waitForTimeout(1_000); // settle any post-idle rendering/toasts
        } catch (err) {
          navError = err instanceof Error ? err.message : String(err);
        }

        const screenshotPath = path.join(SCREENSHOT_DIR, `${slug(route)}.png`);
        try {
          await page.screenshot({ path: screenshotPath, fullPage: true });
        } catch {
          // best-effort — a failed nav can leave nothing paintable
        }
        await page.close();

        results.push({ route, consoleErrors, httpErrors, screenshot: screenshotPath });

        // Record-don't-fail for same-origin 4xx and all cross-origin errors
        // (the qa agent adjudicates those); only same-origin 5xx and console
        // errors fail the route, per PROBE-P7-12.
        const sameOriginFatal = httpErrors.some((e) => {
          try {
            return new URL(e.url).host === BASE_HOST && e.status >= 500;
          } catch {
            return false;
          }
        });

        expect.soft(consoleErrors, `console errors on ${route}`).toHaveLength(0);
        expect
          .soft(sameOriginFatal, `same-origin 5xx on ${route}: ${JSON.stringify(httpErrors)}`)
          .toBe(false);
        expect.soft(navError, `navigation error on ${route}`).toBeNull();
      }
    } finally {
      // Always write the artifact, even if some routes above failed their
      // soft assertions or navigation errored out.
      fs.mkdirSync(EVIDENCE_ROOT, { recursive: true });
      fs.writeFileSync(SUMMARY_PATH, JSON.stringify(results, null, 2));
    }
  });
});
