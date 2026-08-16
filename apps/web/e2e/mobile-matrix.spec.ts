import { test, expect, type Page } from "@playwright/test";

/**
 * S-UI-B4-MOBILE / R1.4 — the mobile responsive-quality matrix.
 *
 * The prior beauty sweep recorded "13/13 routes CONCERN (overflow, sub-12px
 * text, sub-44px tap targets)". This spec is that verdict turned into an
 * executable, repeatable gate: every primary route is measured at 390x844 for
 * the three failure classes, and the suite is green only when ALL routes PASS.
 *
 * Three checks per route:
 *   1. No horizontal overflow — document.scrollWidth must not exceed
 *      clientWidth by more than the established 5px tolerance (same rule as
 *      ml-admin-002 / ml-fe-polish; sub-pixel scrollbar rounding).
 *   2. No sub-12px rendered text — every VISIBLE element that owns a
 *      non-empty text node must compute to font-size >= 12px on mobile.
 *      (Desktop keeps the design system's 10/11px micro-type roles; the
 *      mobile floor lives in globals.css under `@media (max-width: 767px)`.)
 *   3. No sub-44px tap targets — every visible interactive element
 *      (link/button/input/select/tab/switch) must present a hit box whose
 *      smaller dimension is >= 44px, EXCEPT true inline links flowing inside
 *      body text (WCAG 2.5.8's inline exception: enlarging them would break
 *      the prose they sit in). Hidden/zero-size elements are ignored.
 *
 * Route coverage:
 *   - Authenticated dashboard routes run in the shared "chromium" project
 *     against the read-only :3100 build (storageState login).
 *   - Public routes (/login, /pricing) run in the same project (they don't
 *     need the session but tolerate it).
 *   - Admin routes are covered on the isolated companion stack (same
 *     E2E_BASE_URL / fixture-admin pattern as ml-admin-002-mobile-overflow,
 *     which this spec extends rather than duplicates).
 */

const VIEWPORT = { width: 390, height: 844 };
const OVERFLOW_TOLERANCE_PX = 5;
const MIN_FONT_PX = 12;
const MIN_TAP_PX = 44;

// Companion-stack coordinates for the admin describe — identical defaults to
// ml-admin-002-mobile-overflow.spec.ts (fixture identities, not credentials).
const ADMIN_BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3010";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "ml-admin-002-local@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "MlAdmin002Test1";

const DASHBOARD_ROUTES: ReadonlyArray<{ route: string; sentinel: RegExp }> = [
  { route: "/dashboard", sentinel: /./ },
  { route: "/dashboard/agents", sentinel: /./ },
  { route: "/dashboard/analytics", sentinel: /./ },
  { route: "/dashboard/answer-bank", sentinel: /./ },
  { route: "/dashboard/applications", sentinel: /./ },
  { route: "/dashboard/approvals", sentinel: /./ },
  { route: "/dashboard/cover-letters", sentinel: /./ },
  { route: "/dashboard/email", sentinel: /./ },
  { route: "/dashboard/interviews", sentinel: /./ },
  { route: "/dashboard/jobs", sentinel: /./ },
  { route: "/dashboard/networking", sentinel: /./ },
  { route: "/dashboard/offers", sentinel: /./ },
  { route: "/dashboard/resume", sentinel: /./ },
  { route: "/dashboard/settings", sentinel: /./ },
  { route: "/dashboard/stories", sentinel: /./ },
];

const PUBLIC_ROUTES = ["/login", "/pricing"] as const;

const ADMIN_ROUTES: ReadonlyArray<{ route: string; heading: RegExp }> = [
  { route: "/admin", heading: /executive/i },
  { route: "/admin/users", heading: /users/i },
  { route: "/admin/subscriptions", heading: /subscriptions/i },
  { route: "/admin/billing", heading: /billing/i },
  { route: "/admin/spend", heading: /spend/i },
  { route: "/admin/health", heading: /health/i },
  { route: "/admin/audit-log", heading: /audit/i },
  { route: "/admin/promos", heading: /promo/i },
  { route: "/admin/settings", heading: /settings/i },
];

type MatrixResult = {
  overflowPx: number;
  subTextViolations: Array<{ tag: string; fs: number; cls: string; txt: string }>;
  tapViolations: Array<{ tag: string; w: number; h: number; cls: string; txt: string }>;
};

/** Runs entirely in the page: measures the three mobile failure classes. */
async function measureMatrix(page: Page): Promise<MatrixResult> {
  return page.evaluate(
    ({ minFont, minTap }) => {
      const visible = (el: Element): boolean => {
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return false;
        const cs = getComputedStyle(el);
        return cs.visibility !== "hidden" && cs.display !== "none" && Number(cs.opacity) !== 0;
      };
      const clsOf = (el: Element): string => {
        const c = (el as HTMLElement).className as unknown;
        if (typeof c === "string") return c;
        const asSvg = c as { baseVal?: string } | null;
        return asSvg && typeof asSvg.baseVal === "string" ? asSvg.baseVal : "";
      };

      const doc = document.documentElement;
      const overflowPx = doc.scrollWidth - doc.clientWidth;

      const subTextViolations: Array<{ tag: string; fs: number; cls: string; txt: string }> = [];
      for (const el of Array.from(document.querySelectorAll("body *"))) {
        if (!visible(el)) continue;
        const ownsText = Array.from(el.childNodes).some(
          (n) => n.nodeType === Node.TEXT_NODE && (n.textContent ?? "").trim().length > 0
        );
        if (!ownsText) continue;
        const fs = parseFloat(getComputedStyle(el).fontSize);
        if (fs < minFont) {
          subTextViolations.push({
            tag: el.tagName.toLowerCase(),
            fs: Math.round(fs * 100) / 100,
            cls: clsOf(el).slice(0, 90),
            txt: (el.textContent ?? "").trim().slice(0, 40),
          });
        }
      }

      const tapViolations: Array<{ tag: string; w: number; h: number; cls: string; txt: string }> = [];
      const interactive = document.querySelectorAll(
        'a[href], button, input, select, textarea, [role="button"], [role="tab"], [role="switch"], [role="checkbox"], [role="menuitem"]'
      );
      for (const el of Array.from(interactive)) {
        if (!visible(el)) continue;
        const r = el.getBoundingClientRect();
        if (Math.min(r.width, r.height) >= minTap) continue;
        // WCAG 2.5.8 inline exception: links flowing inside body text.
        const cs = getComputedStyle(el);
        const isInlineTextLink =
          el.tagName === "A" && cs.display === "inline" && !!el.closest("p, li, td, span, label");
        if (isInlineTextLink) continue;
        tapViolations.push({
          tag: el.tagName.toLowerCase(),
          w: Math.round(r.width),
          h: Math.round(r.height),
          cls: clsOf(el).slice(0, 90),
          txt: (
            el.getAttribute("aria-label") ??
            el.textContent ??
            el.getAttribute("placeholder") ??
            ""
          )
            .trim()
            .slice(0, 40),
        });
      }

      return { overflowPx, subTextViolations, tapViolations };
    },
    { minFont: MIN_FONT_PX, minTap: MIN_TAP_PX }
  );
}

function assertMatrix(route: string, m: MatrixResult) {
  expect(
    m.overflowPx,
    `${route}: horizontal overflow of ${m.overflowPx}px at 390px (limit ${OVERFLOW_TOLERANCE_PX}px)`
  ).toBeLessThanOrEqual(OVERFLOW_TOLERANCE_PX);
  expect(
    m.subTextViolations,
    `${route}: ${m.subTextViolations.length} visible element(s) render text below ${MIN_FONT_PX}px on mobile — ` +
      JSON.stringify(m.subTextViolations.slice(0, 8))
  ).toHaveLength(0);
  expect(
    m.tapViolations,
    `${route}: ${m.tapViolations.length} interactive element(s) below the ${MIN_TAP_PX}px tap-target floor — ` +
      JSON.stringify(m.tapViolations.slice(0, 8))
  ).toHaveLength(0);
}

async function settle(page: Page) {
  // Dashboards poll live data, so "networkidle" never settles (MP-036 rule):
  // wait for "load", the main landmark, then a fixed paint allowance for the
  // client-side fetches these pages render from.
  await page.getByRole("main").first().waitFor({ state: "visible", timeout: 20_000 });
  await page.waitForTimeout(3_000);
}

test.describe("S-UI-B4-MOBILE matrix — authenticated dashboard routes at 390x844", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
  });

  for (const { route } of DASHBOARD_ROUTES) {
    test(`mobile matrix PASS on ${route}`, async ({ page }) => {
      await page.goto(route, { waitUntil: "load" });
      await settle(page);
      assertMatrix(route, await measureMatrix(page));
    });
  }
});

test.describe("S-UI-B4-MOBILE matrix — public routes at 390x844", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
  });

  for (const route of PUBLIC_ROUTES) {
    test(`mobile matrix PASS on ${route}`, async ({ page }) => {
      await page.goto(route, { waitUntil: "load" });
      await page.waitForTimeout(2_000);
      assertMatrix(route, await measureMatrix(page));
    });
  }
});

test.describe("S-UI-B4-MOBILE matrix — admin routes at 390x844 (companion stack)", () => {
  // Same isolated-stack pattern as ml-admin-002-mobile-overflow: own baseURL,
  // own fixture admin, no shared storageState.
  test.use({ baseURL: ADMIN_BASE_URL, storageState: undefined });

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto("/login");
    await page.getByLabel("Email").fill(ADMIN_EMAIL);
    await page.getByLabel("Password").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.waitForURL("**/dashboard", { timeout: 20_000 });
  });

  for (const { route, heading } of ADMIN_ROUTES) {
    test(`mobile matrix PASS on ${route}`, async ({ page }) => {
      await page.goto(route, { waitUntil: "load" });
      // AdminGuard shows "Verifying admin access..." before the real chrome —
      // wait for the actual page heading before measuring (ml-admin-002 rule).
      await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible({
        timeout: 15_000,
      });
      await page.waitForTimeout(2_000);
      assertMatrix(route, await measureMatrix(page));
    });
  }
});
