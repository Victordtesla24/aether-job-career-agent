import { test, expect } from "@playwright/test";

/**
 * ML-admin-002 (MEDIUM) — mobile 390px horizontal overflow on /admin/settings
 * and /admin/users.
 *
 * Reported overflow: /admin/settings ~25px, /admin/users ~74px, at a 390px
 * viewport (iPhone-class mobile width). Suspected cause: the shared admin
 * shell (apps/web/src/components/admin/admin-shell.tsx) renders a
 * non-responsive fixed `w-56` (224px) sidebar with no mobile breakpoint,
 * plus fixed-width children on the affected pages.
 *
 * CONTRACT PINNED FOR THE FIXER: at a 390px-wide viewport, every /admin/*
 * page must render with NO horizontal overflow — i.e.
 * `document.documentElement.scrollWidth` must not exceed the viewport
 * width (a small +5px tolerance is allowed, matching the existing
 * dashboard mobile-regression convention in e2e/mobile-regression.spec.ts).
 * A fix must make the sidebar collapse/hide (or become an off-canvas
 * drawer) below a responsive breakpoint, and any fixed-width table/form
 * children must become responsive (e.g. horizontal scroll CONFINED to an
 * inner `overflow-x-auto` wrapper, never leaking to the document).
 *
 * This spec runs against a locally-managed API+web pair (own ports, own
 * `aether_test`-schema admin user) rather than the shared authenticated
 * "chromium" project/storageState, so it deliberately overrides `baseURL`
 * and performs its own login — see ML-admin-002 test-authoring notes in
 * uat/reports/evidence/models-live/ for how to point this at another
 * running instance (E2E_BASE_URL / E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD env
 * vars, all with defaults matching that local setup).
 */

const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3010";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "ml-admin-002-local@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "MlAdmin002Test1";
const VIEWPORT = { width: 390, height: 844 };
const OVERFLOW_TOLERANCE_PX = 5;

test.use({ baseURL: BASE_URL, storageState: undefined });

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard", { timeout: 20_000 });
}

async function assertNoHorizontalOverflow(
  page: import("@playwright/test").Page,
  route: string,
  headingName: RegExp
) {
  await page.setViewportSize(VIEWPORT);
  await page.goto(route, { waitUntil: "networkidle" });

  // AdminGuard (apps/web/src/components/admin/admin-shell.tsx's caller,
  // apps/web/src/components/admin/admin-guard.tsx) renders a "Verifying
  // admin access…" placeholder — with none of the real admin chrome/sidebar
  // — until its own client-side isAdmin check resolves; "networkidle"
  // alone can settle before that resolves, so wait for the real page
  // heading (the actual admin-shell content) before measuring.
  await expect(page.getByRole("heading", { name: headingName })).toBeVisible({
    timeout: 15_000,
  });

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));

  const overflowPx = scrollWidth - clientWidth;
  expect(
    overflowPx,
    `${route}: document.scrollWidth (${scrollWidth}px) exceeds the 390px ` +
      `viewport's clientWidth (${clientWidth}px) by ${overflowPx}px — ` +
      `horizontal overflow at mobile width (ML-admin-002; expected <= ` +
      `${OVERFLOW_TOLERANCE_PX}px tolerance)`
  ).toBeLessThanOrEqual(OVERFLOW_TOLERANCE_PX);
}

test.describe("ML-admin-002: admin panel mobile (390px) horizontal overflow", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await login(page);
  });

  test("no horizontal overflow on /admin/settings at 390px", async ({ page }) => {
    await assertNoHorizontalOverflow(page, "/admin/settings", /^Settings$/);
  });

  test("no horizontal overflow on /admin/users at 390px", async ({ page }) => {
    await assertNoHorizontalOverflow(page, "/admin/users", /^Users$/);
  });
});
