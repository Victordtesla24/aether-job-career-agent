import { test, expect, type Page } from "@playwright/test";

/**
 * ML-fe-polish live-repro specs (MODELS-LIVE §7 step 2, batch-4 FE-polish
 * findings). Mirrors the ML-admin-002 / ml-agents-refix local-repro
 * pattern: own throwaway user per test, own locally-managed API+web pair
 * (never the shared authenticated "chromium" project/storageState from
 * ./playwright.config.ts, which points at the DEPLOYED app on port 3000).
 *
 * Run: apps/web$ ./node_modules/.bin/playwright test \
 *        --config=e2e/ml-fe-polish.playwright.config.ts
 */

const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3091";
const OVERFLOW_TOLERANCE_PX = 5;
const MOBILE_VIEWPORT = { width: 390, height: 844 };
const DESKTOP_VIEWPORT = { width: 1440, height: 900 };

test.use({ baseURL: BASE_URL, storageState: undefined });

function uniqueEmail(tag: string): string {
  return `ml-fe-polish-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
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

async function scrollOverflow(page: Page): Promise<{ scrollWidth: number; clientWidth: number }> {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
}

/** next dev compiles each route on-demand; a page's FIRST hit can exceed
 *  Playwright's default 30s navigation timeout and surface as a confusing
 *  net::ERR_ABORTED rather than a clean timeout. Navigate with a generous
 *  timeout so a slow first compile is never mistaken for this finding's
 *  actual (post-compile, fast) overflow measurement. */
async function gotoWarm(page: Page, path: string): Promise<void> {
  await page.goto(path, { timeout: 90_000, waitUntil: "load" });
}

test.describe("ML-settings-001: oversized-field 422 causes horizontal overflow (live repro)", () => {
  async function reproOversizedFieldOverflow(page: Page, tag: string, viewport: { width: number; height: number }) {
    await page.setViewportSize(viewport);
    await signupAndLogin(page, tag);

    await gotoWarm(page, "/dashboard/settings");
    const fullNameInput = page.getByTestId("settings-fullname");
    await expect(fullNameInput).toBeVisible({ timeout: 20_000 });

    // A brand-new signup's targetRole/location come back blank from GET
    // /workspaces/settings — settings-client.tsx's OWN client-side
    // validation (unrelated to this finding) refuses to even attempt a
    // save while those are empty ("Fix the highlighted fields before
    // saving."), which would silently never reach the backend 422 this
    // finding is about. Fill them with harmless valid values so the save
    // actually proceeds to PUT /workspaces/settings.
    await page.getByTestId("settings-targetrole").fill("Staff Engineer");
    await page.getByTestId("settings-location").fill("Sydney, AU");

    const hugeValue = "X".repeat(5000);
    await fullNameInput.fill(hugeValue);

    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/workspaces/settings") && r.request().method() === "PUT"),
      page.getByTestId("save-settings-btn").click(),
    ]);
    expect(response.status(), "expected the backend to correctly 422 an oversized fullName").toBe(422);

    // Give the error banner a moment to paint before measuring.
    await page.waitForTimeout(300);

    const { scrollWidth, clientWidth } = await scrollOverflow(page);
    const overflowPx = scrollWidth - clientWidth;
    expect(
      overflowPx,
      `/dashboard/settings at ${viewport.width}px after an oversized-field 422: ` +
        `document.scrollWidth (${scrollWidth}px) exceeds clientWidth (${clientWidth}px) by ` +
        `${overflowPx}px — the raw echoed Pydantic error is blowing out page layout ` +
        `(ML-settings-001; expected <= ${OVERFLOW_TOLERANCE_PX}px tolerance)`,
    ).toBeLessThanOrEqual(OVERFLOW_TOLERANCE_PX);
  }

  test("no horizontal overflow at 390px mobile after the oversized-field 422", async ({ page }) => {
    await reproOversizedFieldOverflow(page, "settings-mobile", MOBILE_VIEWPORT);
  });

  test("no horizontal overflow at 1440px desktop after the oversized-field 422", async ({ page }) => {
    await reproOversizedFieldOverflow(page, "settings-desktop", DESKTOP_VIEWPORT);
  });
});

test.describe("ML-resume-002: no horizontal overflow at 390px on /dashboard/resume", () => {
  test("document.scrollWidth does not exceed the 390px viewport", async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await signupAndLogin(page, "resume");

    // The reported overflow (uat/reports/evidence/models-live/screens/
    // agent-running/findings.json ML-resume-002) was measured on an account
    // with BOTH a base résumé and a tailored version — the Original/Tailored
    // hero cards (data-design-id="pane-original-rs04" / "pane-tailored-rs05")
    // and the version-compare panel only render their real (non-empty-state)
    // content, including the `tailoredResume.label` pill
    // (`Tailored — <role> @ <company>`, an unbroken string with no wrap
    // points), once BOTH exist — a single résumé alone (confirmed by hand
    // via a standalone diagnostic before writing this spec) does NOT
    // reproduce any overflow. Register a base résumé via the same
    // JSON-ingest endpoint the Resume Studio "paste text" affordance uses
    // (POST /resumes — deterministic, no LLM cost), then a second résumé
    // whose label starts with "Tailored" (the exact string
    // apps/web/src/app/dashboard/resume/page.tsx's `tailoredResume =
    // resumes.find(r => r.label?.startsWith("Tailored"))` selects on) so
    // this spec reproduces the SAME populated-hero-card condition
    // production was actually found in.
    const token = await page.evaluate(() => window.localStorage.getItem("aether_token"));
    const createBase = await page.request.post("/api/resumes", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        label: "Base resume",
        raw_text:
          "Jamie Rivera\nStaff Software Engineer\n\n" +
          "Experience\n- Led a cross-functional platform migration serving 2M+ monthly users.\n" +
          "- Reduced infrastructure cost 34% via a multi-region autoscaling redesign.\n" +
          "- Mentored 6 engineers across 3 product teams.\n",
        contact: { name: "Jamie Rivera", title: "Staff Software Engineer" },
      },
    });
    expect(createBase.status(), "expected the base résumé to register cleanly").toBe(201);

    const createTailored = await page.request.post("/api/resumes", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        label: "Tailored — Senior Platform Engineer @ Example Corp",
        raw_text:
          "Jamie Rivera\nSenior Platform Engineer\n\n" +
          "Experience\n- Led a cross-functional platform migration serving 2M+ monthly users.\n" +
          "- Reduced infrastructure cost 34% via a multi-region autoscaling redesign.\n" +
          "- Mentored 6 engineers across 3 product teams.\n",
        contact: { name: "Jamie Rivera", title: "Senior Platform Engineer" },
      },
    });
    expect(createTailored.status(), "expected the tailored résumé to register cleanly").toBe(201);

    await gotoWarm(page, "/dashboard/resume");
    await expect(page.getByRole("heading", { name: "Resume", level: 1 })).toBeVisible({ timeout: 20_000 });
    // Wait for real content to settle (versions panel resolves from the API,
    // matching the existing resume.spec.ts convention) before measuring —
    // measuring right after navigation risks undercounting still-resolving
    // client content, the lesson already learned from ML-admin-002.
    const versionCard = page.getByTestId("resume-version-card").first();
    const emptyState = page.getByText(/no resume versions yet/i);
    await expect(versionCard.or(emptyState).first()).toBeVisible({ timeout: 20_000 });
    // The two glass hero cards this finding is about only render their real
    // (non-empty-state) content once both résumés we just registered have
    // been fetched and identity-derived — wait for that before measuring.
    await expect(page.getByTestId("hero-original-name")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("hero-tailored-name")).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(300);

    const { scrollWidth, clientWidth } = await scrollOverflow(page);
    const overflowPx = scrollWidth - clientWidth;
    expect(
      overflowPx,
      `/dashboard/resume: document.scrollWidth (${scrollWidth}px) exceeds the 390px ` +
        `viewport's clientWidth (${clientWidth}px) by ${overflowPx}px — horizontal overflow ` +
        `at mobile width (ML-resume-002; expected <= ${OVERFLOW_TOLERANCE_PX}px tolerance)`,
    ).toBeLessThanOrEqual(OVERFLOW_TOLERANCE_PX);
  });
});

/**
 * Populate a REAL AgentRun row and land on /dashboard/agents with it
 * rendered before measuring: fitScorer is deterministic (no LLM cost) and
 * honestly refuses with 422 for a resume-less throwaway account (README
 * §"AI Agents" / apps/api/app/agents/fit_scorer.py) — this is exactly the
 * same free/fast/deterministic mechanism the platform documents, and it
 * leaves a real "failed" AgentRun row with a genuine, non-wrapping error
 * string behind, which is what the Agent Orchestration panel's Error Log
 * (Orchestration.tsx `data-testid="error-log"`, `className="truncate …"`
 * with no ancestor min-width:0) renders — the root cause this finding pins.
 * Triggered via a raw API call (not the UI) so this spec doesn't depend on
 * discovering whatever per-agent "Run" control exists elsewhere on the page.
 *
 * Retries with a brand-new throwaway user on failure: the shared
 * `aether_test` Postgres schema is used concurrently by other swarm
 * sessions' pytest runs, which TRUNCATE/lazily-recreate tables between
 * their own tests (documented cross-swarm flakiness — a concurrent
 * TRUNCATE/DDL race can transiently 401/404/500 an otherwise-correct
 * request for a completely unrelated user). A same-shaped retry with a
 * fresh user distinguishes that transient infra noise from a real defect.
 */
async function setupAgentsWithRealErrorLogEntry(page: Page, tag: string): Promise<void> {
  const MAX_ATTEMPTS = 3;
  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      await signupAndLogin(page, `${tag}-a${attempt}`);
      const token = await page.evaluate(() => window.localStorage.getItem("aether_token"));
      expect(token, "expected a stored session token after signup+login").toBeTruthy();
      const runResponse = await page.request.post("/api/agents/fit-scorer/run", {
        headers: { Authorization: `Bearer ${token}` },
        data: {},
      });
      // Either outcome is fine for this repro — an honest 422 no-resume
      // refusal (expected for a fresh signup) or, if a base resume already
      // resolves for some reason, a 200 completed run. Either way an
      // AgentRun row now exists for the Error Log / Task Queue to render.
      if (![200, 422].includes(runResponse.status())) {
        throw new Error(`POST /agents/fit-scorer/run unexpected status ${runResponse.status()}`);
      }

      await gotoWarm(page, "/dashboard/agents");
      await expect(page.getByTestId("agent-configuration")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("agent-orchestration")).toBeVisible({ timeout: 20_000 });
      // Wait for the Error Log to show the real run entry rather than its
      // "No log entries yet." empty state, so the truncate/nowrap span this
      // finding is about has actually rendered before measuring (mirrors the
      // ML-admin-002 lesson: measure after real content settles).
      await expect(page.getByTestId("error-log")).not.toContainText(/no log entries yet/i, {
        timeout: 15_000,
      });
      return;
    } catch (e) {
      lastError = e;
    }
  }
  throw new Error(
    `setupAgentsWithRealErrorLogEntry: gave up after ${MAX_ATTEMPTS} attempts — last error: ${
      lastError instanceof Error ? lastError.message : String(lastError)
    }`,
  );
}

test.describe("ML-agents-006: no horizontal overflow at 390px on /dashboard/agents (Orchestration panel)", () => {
  test("document.scrollWidth does not exceed the 390px viewport after a real run populates the Orchestration panel", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await setupAgentsWithRealErrorLogEntry(page, "agents");
    await page.waitForTimeout(300);

    const { scrollWidth, clientWidth } = await scrollOverflow(page);
    const overflowPx = scrollWidth - clientWidth;
    expect(
      overflowPx,
      `/dashboard/agents: document.scrollWidth (${scrollWidth}px) exceeds the 390px ` +
        `viewport's clientWidth (${clientWidth}px) by ${overflowPx}px — horizontal overflow ` +
        `at mobile width (ML-agents-006; expected <= ${OVERFLOW_TOLERANCE_PX}px tolerance)`,
    ).toBeLessThanOrEqual(OVERFLOW_TOLERANCE_PX);
  });

  test("component contract: the Orchestration 3-column row's children never exceed their own section's width", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await setupAgentsWithRealErrorLogEntry(page, "agents-component");
    const orchestration = page.getByTestId("agent-orchestration");
    await page.waitForTimeout(300);

    // The DOM-offender-sweep technique from the adversarial verification
    // (uat/reports/evidence/models-live/adversarial/batch2-prodverify.md):
    // the parent section is already correctly sized to the viewport; the
    // pinned contract is that the 3-column row's children (task-queue,
    // performance-metrics, error-log — the `grid gap-4 xl:grid-cols-3` in
    // Orchestration.tsx) must be constrained BY that parent, never wider
    // than it — a real, layout-engine measurement of exactly the
    // min-w-0-on-a-grid-item defect, independent of whatever CSS technique
    // (min-w-0, overflow-hidden, responsive stacking) the fix ultimately uses.
    const parentWidth = await orchestration.evaluate((el) => el.getBoundingClientRect().width);
    for (const testId of ["task-queue", "performance-metrics", "error-log"]) {
      const child = page.getByTestId(testId);
      await expect(child).toBeVisible();
      const childWidth = await child.evaluate((el) => el.getBoundingClientRect().width);
      expect(
        childWidth,
        `[data-testid="${testId}"] is ${childWidth}px wide — wider than its own parent ` +
          `[data-testid="agent-orchestration"] (${parentWidth}px) — a CSS Grid item with no ` +
          `min-width:0 escaping an already-correctly-sized parent (ML-agents-006)`,
      ).toBeLessThanOrEqual(parentWidth + OVERFLOW_TOLERANCE_PX);
    }
  });
});
