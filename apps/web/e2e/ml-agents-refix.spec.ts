import { test, expect, type Page } from "@playwright/test";

/**
 * ML-agents-refix live-repro specs (MODELS-LIVE §7 step 2), Agents screen:
 *
 *   * ML-agents-002 (HIGH) — after saving a specific model for an LLM agent
 *     via its per-agent picker and reloading the page, the "Model for this
 *     agent" display reverts to the env-default model instead of showing
 *     the model the user actually saved. The config itself DOES persist
 *     (apps/api/tests/test_ml_agents_refix.py pins the write+read-back
 *     contract at the API layer) — this is a DISPLAY bug: `GET
 *     /agents/catalog` computes each agent's `model` field via
 *     `_model_for_agent(backend)` with NO `override` argument
 *     (apps/api/app/routers/agents.py ~1725), so it always resolves to
 *     `get_model(tier)` (the env default) and never consults
 *     `_user_model_override(user_id, backend)` — even though that exact
 *     helper is what every REAL run and the billing audit already use. A
 *     mocked FE unit test can't catch this because the mock controls what
 *     `fetchCatalog()` returns; only a REAL round trip through the real
 *     backend catches the backend computing the wrong value in the first
 *     place — hence this live-repro instead of a vitest component test.
 *     CONTRACT PINNED FOR THE FIXER: `agent_catalog()` must pass
 *     `override=_user_model_override(user_id, backend)` into
 *     `_model_for_agent(...)`, exactly like `_billing_audit` /
 *     `_execute_reserved_run` already do.
 *
 *   * ML-agents-005 (MEDIUM) — at a 390px mobile viewport, the per-agent
 *     model picker's price/context badges
 *     (AgentModelPicker.tsx's `<div className="mt-0.5 flex flex-wrap ...">`
 *     row) are not fully contained, causing horizontal overflow on
 *     /dashboard/agents. CONTRACT PINNED FOR THE FIXER: at 390px,
 *     `document.documentElement.scrollWidth` must not exceed the viewport's
 *     `clientWidth` by more than a small tolerance — mirrors the existing
 *     ML-admin-002 mobile-overflow convention
 *     (e2e/ml-admin-002-mobile-overflow.spec.ts).
 *
 * Both specs run against a LOCALLY-MANAGED API+web pair (own dedicated
 * ports, own throwaway signed-up user) rather than the shared authenticated
 * "chromium" project/storageState from ./playwright.config.ts, which points
 * at the DEPLOYED app on port 3000 — reusing it here would mutate real
 * AgentConfig rows for the shared session's account. See
 * ml-agents-refix.playwright.config.ts and the ml-agents-refix-start-{api,web}.sh
 * scripts (scratchpad) for how that pair was started; override E2E_BASE_URL
 * to point this at a different already-running instance.
 *
 * Run: apps/web$ ./node_modules/.bin/playwright test \
 *        --config=e2e/ml-agents-refix.playwright.config.ts
 */

const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3012";
const VIEWPORT = { width: 390, height: 844 };
const OVERFLOW_TOLERANCE_PX = 5;

test.use({ baseURL: BASE_URL, storageState: undefined });

function uniqueEmail(tag: string): string {
  return `ml-agents-refix-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/** Self-service /signup + auto-login (own throwaway user, never the shared
 *  demo/admin credential) — asserts the redirect to /dashboard so a signup
 *  regression fails loudly here instead of masquerading as an unrelated
 *  failure further down the test. */
async function signupAndLogin(page: Page, tag: string): Promise<void> {
  const email = uniqueEmail(tag);
  const password = "Sup3rSecret1";
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.locator("#signup-consent").check();
  await page.getByRole("button", { name: /create account/i }).click();
  await page.waitForURL("**/dashboard", { timeout: 20_000 });
}

test.describe("ML-agents-002: saved per-agent model survives reload", () => {
  test("selecting a model for resumeTailoring and reloading still shows THAT model, not the default", async ({
    page,
  }) => {
    await signupAndLogin(page, "002");

    await page.goto("/dashboard/agents");
    await expect(page.getByTestId("agent-configuration")).toBeVisible({ timeout: 20_000 });
    const picker = page.getByTestId("agent-model-picker-resumeTailoring");
    await expect(picker).toBeVisible({ timeout: 20_000 });
    // Wait for the live OpenRouter catalog to actually finish loading (its
    // search box present) before reading the current model / picking a row.
    await expect(
      picker.getByTestId("agent-model-search-resumeTailoring"),
    ).toBeVisible({ timeout: 20_000 });

    const before = (await picker.locator("span.font-mono").first().textContent())?.trim();

    // Pick the FIRST rendered model option that differs from the current
    // selection — robust to whatever the live catalog returns today.
    const options = picker.locator('[data-testid^="model-option-"]');
    await expect(options.first()).toBeVisible({ timeout: 20_000 });
    const count = await options.count();
    let chosenId: string | null = null;
    for (let i = 0; i < count; i++) {
      const el = options.nth(i);
      const testid = await el.getAttribute("data-testid");
      const id = testid?.replace(/^model-option-/, "") ?? null;
      if (id && id !== before) {
        await el.click();
        chosenId = id;
        break;
      }
    }
    expect(
      chosenId,
      "expected at least one selectable model different from the current default",
    ).not.toBeNull();

    // Success notice confirms the PUT round-tripped; then wait for the
    // "saving…" flag to clear (set false only after the post-save catalog
    // refetch resolves) before reloading.
    await expect(page.getByTestId("agents-notice")).toContainText(/model updated/i, {
      timeout: 20_000,
    });
    await expect(picker.getByText(/saving/i)).toHaveCount(0, { timeout: 20_000 });

    await page.reload();
    await expect(page.getByTestId("agent-configuration")).toBeVisible({ timeout: 20_000 });
    const pickerAfter = page.getByTestId("agent-model-picker-resumeTailoring");
    await expect(
      pickerAfter.getByTestId("agent-model-search-resumeTailoring"),
    ).toBeVisible({ timeout: 20_000 });

    const after = (await pickerAfter.locator("span.font-mono").first().textContent())?.trim();

    expect(
      after,
      `ML-agents-002: after reload the "Model for this agent" display showed ` +
        `${JSON.stringify(after)} — expected the just-saved ${JSON.stringify(chosenId)}. ` +
        "The config persisted (see the backend round-trip pin in " +
        "test_ml_agents_refix.py), so the UI is reading the wrong source " +
        "(GET /agents/catalog's env-default model, not the saved AgentConfig.model).",
    ).toBe(chosenId);
  });
});

test.describe("ML-agents-005: no horizontal overflow at 390px on the Agents screen", () => {
  test("agent model picker price badges do not overflow the 390px viewport", async ({ page }) => {
    await signupAndLogin(page, "005");
    await page.setViewportSize(VIEWPORT);
    await page.goto("/dashboard/agents");

    await expect(page.getByTestId("agent-configuration")).toBeVisible({ timeout: 20_000 });
    // Wait for a real per-agent picker to finish loading the live catalog
    // (its search box present) so the price-badge rows this finding is
    // about have actually rendered before measuring — matches the
    // ML-admin-002 lesson learned (measuring right after "networkidle"
    // undercounts because client-side content is still resolving).
    await expect(
      page.getByTestId("agent-model-search-resumeTailoring"),
    ).toBeVisible({ timeout: 20_000 });

    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));

    const overflowPx = scrollWidth - clientWidth;
    expect(
      overflowPx,
      `/dashboard/agents: document.scrollWidth (${scrollWidth}px) exceeds the ` +
        `390px viewport's clientWidth (${clientWidth}px) by ${overflowPx}px — ` +
        "horizontal overflow at mobile width (ML-agents-005; expected <= " +
        `${OVERFLOW_TOLERANCE_PX}px tolerance)`,
    ).toBeLessThanOrEqual(OVERFLOW_TOLERANCE_PX);
  });
});
