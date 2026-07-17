import { test, expect, request as apiRequest } from "@playwright/test";

/**
 * GAP-P7-DEF-B (PROBE-P7-09): /dashboard/settings save fails for a stored
 * reserved-TLD email such as ``admin@aether.local`` — PUT /workspaces/settings
 * returns 422 ("special-use or reserved name") because Pydantic's EmailStr
 * rejects the domain regardless of `check_deliverability`
 * (apps/api/app/routers/workspaces.py:625). Approved fix (§15.2, NOT yet
 * implemented as of this commit — TDD fail-before, see
 * apps/api/tests/test_gap_p7_def_b_email_validation.py for the backend
 * contract tests): an ``AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS`` startup
 * allowlist (default "aether.local") discards the matching entry from
 * `email_validator.SPECIAL_USE_DOMAIN_NAMES`.
 *
 * These two specs describe the TARGET behaviour on /dashboard/settings:
 *   1. an account whose stored email already ends in "@aether.local" can
 *      save an unrelated profile change (display name) without the save
 *      failing;
 *   2. a syntactically invalid email keeps showing an inline validation
 *      error and never reaches the backend (this half already works today
 *      — the client-side EMAIL_RE check in
 *      apps/web/src/app/dashboard/settings/page.tsx runs before any PUT is
 *      attempted — kept here as a paired regression guard per the gap's
 *      tests_required list, "e2e gap_p7_def_b.spec.ts").
 *
 * PATTERN: copied from apps/web/e2e/phase7-route-sweep.spec.ts (untracked,
 * main tree only — read directly from
 * /home/ubuntu/github_repos/aether-job-career-agent/apps/web/e2e/phase7-route-sweep.spec.ts
 * for this fixer's reference copy). Same self-contained approach: API login
 * (POST {BASE_URL}/api/auth/login) followed by injecting the returned
 * access_token into localStorage under the "aether_token" key via
 * context.addInitScript, with `test.use({ storageState: {...} })` clearing
 * any project-level storageState so this file never depends on
 * e2e/.auth/user.json existing. This spec is NOT run against production by
 * this fixer — STEP-7 is TDD-only; only `npx playwright test --list` is
 * used to confirm it parses. A future qa/fixer run is expected to actually
 * execute it once GAP-P7-DEF-B's fix lands.
 *
 * CREDENTIALS: [ASSUMED-PENDING-PROBE] — AETHER_E2E_EMAIL/AETHER_E2E_PASSWORD
 * default to "admin"/"admin123" (same default as phase7-route-sweep.spec.ts,
 * itself unverified against the seeded DB by that fixer). GAP-P7-DEF-B's own
 * "observed" line records exactly one stored row affected —
 * `admin@aether.local` — which is consistent with this being the seeded
 * admin account, but that has NOT been independently re-probed by this
 * fixer (test-only change, no DB access taken in this STEP-7 pass). Set the
 * env vars explicitly for a real run instead of relying on the default.
 */

test.use({ storageState: { cookies: [], origins: [] } });

const BASE_URL = (process.env.BASE_URL || "https://5cb5f0620.abacusai.cloud").replace(/\/+$/, "");
const API_BASE = `${BASE_URL}/api`;
const TOKEN_STORAGE_KEY = "aether_token";

const E2E_EMAIL = process.env.AETHER_E2E_EMAIL || "admin";
const E2E_PASSWORD = process.env.AETHER_E2E_PASSWORD || "admin123";

async function getAuthToken(): Promise<string> {
  const ctx = await apiRequest.newContext();
  try {
    const res = await ctx.post(`${API_BASE}/auth/login`, {
      data: { email: E2E_EMAIL, password: E2E_PASSWORD },
    });
    if (!res.ok()) {
      throw new Error(
        `gap_p7_def_b login failed: HTTP ${res.status()} for "${E2E_EMAIL}" against ` +
          `${API_BASE}/auth/login — set AETHER_E2E_EMAIL/AETHER_E2E_PASSWORD to a real account.`,
      );
    }
    const body = (await res.json()) as { access_token?: string };
    if (!body.access_token) {
      throw new Error("gap_p7_def_b login response missing access_token");
    }
    return body.access_token;
  } finally {
    await ctx.dispose();
  }
}

async function loginAndOpenSettings(context: import("@playwright/test").BrowserContext) {
  const token = await getAuthToken();
  await context.addInitScript(
    ({ key, value }) => window.localStorage.setItem(key, value),
    { key: TOKEN_STORAGE_KEY, value: token },
  );
  const page = await context.newPage();
  await page.goto(`${BASE_URL}/dashboard/settings`, { waitUntil: "networkidle", timeout: 45_000 });
  await expect(page.getByTestId("settings-page")).toBeVisible({ timeout: 15_000 });
  return page;
}

test.describe("GAP-P7-DEF-B: internal-use email allowlist on /dashboard/settings", () => {
  test("settings_save_with_existing_aether_local_email_succeeds", async ({ context }) => {
    const page = await loginAndOpenSettings(context);

    // Precondition for this to be a meaningful reproduction of the gap: the
    // account's stored email already ends in "@aether.local" (the one
    // production row the gap record names). If a differently-configured
    // account is used, this soft-checks rather than hard-fails so the test
    // still exercises the save path.
    const emailValue = await page.getByTestId("settings-email").inputValue();
    expect.soft(emailValue.endsWith("@aether.local"), `expected a stored @aether.local email, got "${emailValue}"`).toBe(true);

    // Change an unrelated field only — the email itself is left untouched,
    // matching the backend's test_email_not_changed_unrelated_field_save_succeeds.
    const nameInput = page.getByTestId("settings-fullname");
    await nameInput.fill("");
    await nameInput.fill(`GAP-P7-DEF-B Probe ${Date.now()}`);

    await page.getByTestId("save-settings-btn").click();

    // Target behaviour: success notice appears, not the top-level error
    // banner ("Fix the highlighted fields before saving." / a 422 message).
    await expect(page.getByTestId("settings-saved-notice")).toBeVisible({ timeout: 15_000 });
  });

  test("settings_save_with_invalid_email_shows_validation_error", async ({ context }) => {
    const page = await loginAndOpenSettings(context);

    const emailInput = page.getByTestId("settings-email");
    await emailInput.fill("");
    await emailInput.fill("not-an-email");

    await page.getByTestId("save-settings-btn").click();

    // Client-side validation (EMAIL_RE in dashboard/settings/page.tsx) must
    // catch this before any PUT is attempted: an inline error next to the
    // email field, plus the top-level "fix the highlighted fields" banner,
    // and no success notice.
    await expect(page.getByText("Enter a valid email address")).toBeVisible();
    await expect(page.getByText("Fix the highlighted fields before saving.")).toBeVisible();
    await expect(page.getByTestId("settings-saved-notice")).toHaveCount(0);
  });
});
