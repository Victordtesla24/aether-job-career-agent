import { test, expect } from "@playwright/test";

/**
 * GOLD-MASTER-V2 §9.2.2 / §9.2.1 (W-G) — admin login entry point.
 *
 * VERIFIED TWICE on production: there is no "Admin Login" link on /login
 * (§9.2.1) and consequently no way for an admin account to be routed to the
 * admin portal (/admin) as part of signing in (§9.2.2) — an admin who signs
 * in via the ordinary form lands on /dashboard exactly like anyone else and
 * must manually type /admin into the URL bar. Everything ELSE about admin
 * access is already built and independently verified correct: all 7
 * /admin/* routes render real data, AdminGuard + the backend AdminUser gate
 * already block non-admins at both layers (12/12 checks, zero leak), and
 * admin mutations already write AdminAuditLog rows. This spec does NOT
 * re-test any of that — only the entry-point gap.
 *
 * This spec runs against a locally-managed, ISOLATED API+web pair (own
 * ports, own `aether_test`-schema fixture users created via direct
 * register+SQL-promote — never the seeded `admin` identifier, which
 * BLOCKER-001's fix, commit 6dcf927, is about to revoke and 401)
 * rather than the shared authenticated "chromium" project/storageState —
 * mirrors the existing convention in
 * apps/web/e2e/ml-admin-002-mobile-overflow.spec.ts (see that file's header
 * for the E2E_BASE_URL / E2E_*_EMAIL / E2E_*_PASSWORD override pattern; the
 * defaults below match a specific local run recorded in
 * uat/reports/evidence/gold-master-v2/waves/WG-NUL-failing-tests.md).
 *
 * Both tests below discover the entry point starting from /login (§9.2.1's
 * own contract) rather than hard-coding a destination page name the fixer
 * hasn't built yet (e.g. never assumes /admin/login specifically) — only the
 * FINAL observable state is asserted: does an admin login end up at /admin
 * (the real, already-existing admin portal route — never an invented
 * /admin/dashboard, per §13.1), and does a non-admin's attempt fail without
 * leaking an admin-specific denial.
 */

const BASE_URL = process.env.WG_E2E_BASE_URL ?? "http://127.0.0.1:3095";
const ADMIN_EMAIL = process.env.WG_E2E_ADMIN_EMAIL ?? "wg-admin-68075c7601@example.com";
const USER_EMAIL = process.env.WG_E2E_USER_EMAIL ?? "wg-user-519a113ab2@example.com";
const PASSWORD = process.env.WG_E2E_PASSWORD ?? "WgE2eTest1";

test.use({ baseURL: BASE_URL, storageState: undefined });

/** Locate the §9.2.1 admin entry point on /login (see wg-admin-entry-004.test.tsx
 * for the equivalent fast component-level check of this same link). */
async function findAdminEntryLink(page: import("@playwright/test").Page) {
  await page.goto("/login");
  return page.getByRole("link", { name: /admin/i });
}

test.describe("W-G §9.2.1/§9.2.2: admin login reaches the admin portal", () => {
  test("an admin login reaches /admin (the real admin portal), not /dashboard", async ({
    page,
  }) => {
    const adminLink = await findAdminEntryLink(page);
    // Fail-before: no such link exists on current code, so this locator
    // never becomes visible and the test fails here — honestly reproducing
    // that the admin login path is unreachable from /login today.
    await expect(
      adminLink,
      "§9.2.1: no 'Admin' entry link found on /login — the admin login path " +
        "is unreachable from the public sign-in screen"
    ).toBeVisible({ timeout: 5_000 });

    await adminLink.click();

    // Whatever page this leads to, it must present a real sign-in form
    // (identifier + password) — same identifier/password contract as the
    // general /login form (POST /auth/login already accepts either).
    await page.getByLabel(/email|username/i).fill(ADMIN_EMAIL);
    await page.getByLabel(/^password$/i).fill(PASSWORD);
    await page.getByRole("button", { name: /sign in|log in/i }).click();

    await page.waitForURL(/\/admin(\/|$|\?)/, { timeout: 15_000 });
    const path = new URL(page.url()).pathname;
    expect(
      path,
      "§9.2.2: an admin login must land on /admin (the existing admin " +
        "portal route) — not /dashboard, and not an invented /admin/dashboard"
    ).toBe("/admin");

    // The real admin shell must actually be showing (AdminGuard resolved
    // isAdmin=true), not a "Verifying admin access…"/denied placeholder.
    await expect(page.getByRole("heading", { name: /overview|health|dashboard/i })).toBeVisible({
      timeout: 10_000,
    });
  });

  test("a non-admin hitting the admin login path is refused honestly, with no user-enumeration signal", async ({
    page,
  }) => {
    const adminLink = await findAdminEntryLink(page);
    await expect(
      adminLink,
      "§9.2.1: no 'Admin' entry link found on /login — cannot exercise the " +
        "refusal contract without the entry point existing"
    ).toBeVisible({ timeout: 5_000 });

    await adminLink.click();

    await page.getByLabel(/email|username/i).fill(USER_EMAIL);
    await page.getByLabel(/^password$/i).fill(PASSWORD);
    await page.getByRole("button", { name: /sign in|log in/i }).click();

    // A real, correctly-authenticated NON-admin must never reach /admin.
    await page.waitForTimeout(2_000);
    const path = new URL(page.url()).pathname;
    expect(path, "a non-admin must never be routed into /admin").not.toBe("/admin");

    // No admin-specific denial message anywhere on the page — a distinct
    // "you are not an administrator" (as opposed to a generic sign-in
    // failure/redirect) would confirm to an attacker that these are valid,
    // real credentials for a non-admin account (a user-enumeration-adjacent
    // signal the brief explicitly calls out).
    const bodyText = (await page.textContent("body")) ?? "";
    expect(
      /not\s+an\s+admin|admin\s+privileges?\s+required|insufficient\s+privilege/i.test(bodyText),
      `page leaked an admin-specific denial message distinguishable from a generic ` +
        `sign-in failure: ${bodyText.slice(0, 300)}`
    ).toBe(false);
  });
});
