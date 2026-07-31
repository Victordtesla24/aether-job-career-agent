/**
 * PROD-VERIFY-5A item 1 (UI half) — the FIVE new agent cards on /dashboard/agents.
 *
 * Asserts, per card, against LIVE production only:
 *   - the card renders and shows status ACTIVE (never "planned"/"Planned");
 *   - the Run button exists and is enabled;
 *   - the settings panel opens, and the model picker is present ONLY for
 *     companyResearch (model-overridable) and absent for the four deterministic
 *     ones — i.e. "configurable per its type";
 *   - the deterministic cards disclose "deterministic" as their model.
 *
 * Read-only: opens panels and reads DOM. It does NOT click Run (the live runs are
 * driven over the API in the sibling evidence files so quota/spend deltas are
 * measured exactly).
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-5a";
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const NEW_AGENTS = [
  { key: "compliance", deterministic: true },
  { key: "salaryIntelligence", deterministic: true },
  { key: "marketTrends", deterministic: true },
  { key: "learningFeedback", deterministic: true },
  { key: "companyResearch", deterministic: false },
];

const consoleErrors = [];
const pageErrors = [];
const failedRequests = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push({ url: page.url(), text: m.text() });
  });
  page.on("pageerror", (e) => pageErrors.push({ url: page.url(), text: String(e) }));
  page.on("requestfailed", (r) =>
    failedRequests.push({ url: r.url(), failure: r.failure()?.errorText })
  );

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', (process.env.LOGIN_EMAIL ?? (() => { throw new Error("LOGIN_EMAIL must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.fill('input[type="password"]', (process.env.LOGIN_PASSWORD ?? (() => { throw new Error("LOGIN_PASSWORD must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });

  await page.goto(`${BASE}/dashboard/agents`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(11000);
  await page.screenshot({ path: path.join(SHOTS, "item1-agents-full.png"), fullPage: true });

  const results = {};
  for (const { key, deterministic } of NEW_AGENTS) {
    const card = page.locator(`[data-testid="agent-card-${key}"]`);
    const present = (await card.count()) > 0;
    const row = { present, cardText: null, runButton: null, modelPicker: null };
    if (present) {
      await card.first().scrollIntoViewIfNeeded();
      row.cardText = (await card.first().innerText()).replace(/\n+/g, " | ");
      const run = page.locator(`[data-testid="agent-run-${key}"]`);
      row.runButton = {
        present: (await run.count()) > 0,
        enabled: (await run.count()) > 0 ? await run.first().isEnabled() : null,
        label: (await run.count()) > 0 ? (await run.first().innerText()).trim() : null,
      };
      await card.first().screenshot({ path: path.join(SHOTS, `item1-card-${key}.png`) });

      // open the per-agent settings panel and look for the model picker
      const toggle = page.locator(`[data-testid="agent-settings-toggle-${key}"]`);
      if ((await toggle.count()) > 0) {
        await toggle.first().click();
        await page.waitForTimeout(4500);
        const picker = page.locator(`[data-testid="agent-model-picker-${key}"]`);
        const panel = page.locator(`[data-testid="agent-settings-${key}"]`);
        row.modelPicker = {
          pickerPresent: (await picker.count()) > 0,
          panelPresent: (await panel.count()) > 0,
          panelText:
            (await panel.count()) > 0
              ? (await panel.first().innerText()).replace(/\n+/g, " | ").slice(0, 700)
              : null,
        };
        await page.screenshot({
          path: path.join(SHOTS, `item1-settings-${key}.png`),
          fullPage: true,
        });
        await toggle.first().click();
        await page.waitForTimeout(1200);
      }
      row.expectModelPicker = !deterministic;
      row.modelPickerVerdict =
        row.modelPicker == null
          ? "NO_PANEL"
          : row.modelPicker.pickerPresent === !deterministic
            ? "PASS"
            : "FAIL";
      row.activeVerdict = /\bActive\b/i.test(row.cardText) && !/\bPlanned\b/i.test(row.cardText)
        ? "PASS"
        : "FAIL";
      row.deterministicDisclosed = /deterministic/i.test(row.cardText);
    }
    results[key] = row;
  }

  const buildId = await page.evaluate(() => {
    const el = document.getElementById("__NEXT_DATA__");
    if (el) { try { return JSON.parse(el.textContent).buildId; } catch { /* noop */ } }
    return (window.__NEXT_DATA__ && window.__NEXT_DATA__.buildId) || null;
  });

  const report = { capturedAt: new Date().toISOString(), base: BASE, buildId, results,
    consoleErrors, pageErrors, failedRequests };
  fs.writeFileSync(path.join(OUT, "80-item1-agents-screen.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ buildId, consoleErrors: consoleErrors.length,
    pageErrors: pageErrors.length, failedRequests: failedRequests.length }, null, 2));
  for (const [k, v] of Object.entries(results)) {
    console.log(`${k}: present=${v.present} active=${v.activeVerdict} run=${JSON.stringify(v.runButton)} pickerVerdict=${v.modelPickerVerdict} detDisclosed=${v.deterministicDisclosed}`);
  }
  await browser.close();
})().catch((e) => { console.error("SCRIPT ERROR", e); process.exit(1); });
