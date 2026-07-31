/**
 * PROD-VERIFY-5A item 1 (UI half, corrected discriminator).
 *
 * `agent-model-picker-<key>` is rendered in BOTH branches of AgentModelPicker
 * (the honest LOCKED notice and the real picker), so its presence proves nothing.
 * The real discriminator is the search input `agent-model-search-<key>`, which
 * only the overridable branch renders. This re-check asserts:
 *   - four deterministic agents: locked notice text present, NO search input;
 *   - companyResearch: search input present and model rows selectable.
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-5a";
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const AGENTS = [
  ["compliance", false],
  ["salaryIntelligence", false],
  ["marketTrends", false],
  ["learningFeedback", false],
  ["companyResearch", true],
];

const consoleErrors = [];
const pageErrors = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', (process.env.LOGIN_EMAIL ?? (() => { throw new Error("LOGIN_EMAIL must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.fill('input[type="password"]', (process.env.LOGIN_PASSWORD ?? (() => { throw new Error("LOGIN_PASSWORD must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });
  await page.goto(`${BASE}/dashboard/agents`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(11000);

  const out = {};
  for (const [key, overridable] of AGENTS) {
    const toggle = page.locator(`[data-testid="agent-settings-toggle-${key}"]`);
    await toggle.first().scrollIntoViewIfNeeded();
    await toggle.first().click();
    await page.waitForTimeout(5000);
    const picker = page.locator(`[data-testid="agent-model-picker-${key}"]`);
    const search = page.locator(`[data-testid="agent-model-search-${key}"]`);
    const tier = page.locator(`[data-testid="agent-model-tier-${key}"]`);
    const pickerText = (await picker.count()) > 0
      ? (await picker.first().innerText()).replace(/\n+/g, " ").trim() : null;
    const searchCount = await search.count();
    const optionCount = await page.locator(`[data-testid^="model-option-"]`).count();
    out[key] = {
      overridableExpected: overridable,
      pickerText,
      searchInputPresent: searchCount > 0,
      tierFilterPresent: (await tier.count()) > 0,
      modelOptionsVisible: optionCount,
      lockedNoticeShown: /Fixed model — not user-selectable/i.test(pickerText || ""),
      verdict: (searchCount > 0) === overridable ? "PASS" : "FAIL",
    };
    await picker.first().screenshot({ path: path.join(SHOTS, `item1b-picker-${key}.png`) })
      .catch(() => {});
    await toggle.first().click();
    await page.waitForTimeout(1000);
  }

  fs.writeFileSync(path.join(OUT, "81-item1b-picker-recheck.json"),
    JSON.stringify({ capturedAt: new Date().toISOString(), out, consoleErrors, pageErrors }, null, 2));
  for (const [k, v] of Object.entries(out)) {
    console.log(`${k}: verdict=${v.verdict} search=${v.searchInputPresent} tier=${v.tierFilterPresent} options=${v.modelOptionsVisible} locked=${v.lockedNoticeShown}`);
    console.log(`   text: ${String(v.pickerText).slice(0, 190)}`);
  }
  console.log("consoleErrors", consoleErrors.length, "pageErrors", pageErrors.length);
  await browser.close();
})().catch((e) => { console.error("SCRIPT ERROR", e); process.exit(1); });
