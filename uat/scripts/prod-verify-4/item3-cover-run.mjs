/**
 * QA #4 item 3 — trigger ONE admin cover-letter run through the real UI on a job
 * that HAS a tailored resume, and verify: letter produced, honest badge, and the
 * AgentRun row records a real model + nonzero cost.
 * Target: LIVE production https://5cb5f0620.abacusai.cloud (external URL only).
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-4";
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });
const WANT = process.env.WANT_JOB || "Samsara";

const consoleErrors = [];
const pageErrors = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push({ url: page.url(), text: m.text() }); });
  page.on("pageerror", (e) => pageErrors.push({ url: page.url(), text: String(e) }));

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', (process.env.LOGIN_EMAIL ?? (() => { throw new Error("LOGIN_EMAIL must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.fill('input[type="password"]', (process.env.LOGIN_PASSWORD ?? (() => { throw new Error("LOGIN_PASSWORD must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });

  await page.goto(`${BASE}/dashboard/cover-letters`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="cover-letter-job-select"]', { timeout: 60000 });
  await page.waitForTimeout(4000);

  const cardsBefore = await page.locator('[data-testid="cover-letter-card"]').count();
  const options = await page.locator('[data-testid="cover-letter-job-select"] option').evaluateAll(
    (els) => els.map((e) => ({ value: e.value, label: e.textContent.trim() }))
  );
  const target = options.find((o) => o.label.includes(WANT) && o.value);
  if (!target) throw new Error(`no option matching ${WANT}; options=${JSON.stringify(options).slice(0, 2000)}`);

  await page.selectOption('[data-testid="cover-letter-job-select"]', target.value);
  await page.screenshot({ path: path.join(SHOTS, "item3b-01-before-run.png"), fullPage: false });

  const tStart = Date.now();
  const startedAtIso = new Date().toISOString();
  await page.click('[data-testid="run-cover-letter-btn"]');

  // Wait for a new card to appear (bounded).
  let cardsAfter = cardsBefore;
  let waited = 0;
  while (waited < 200000) {
    await page.waitForTimeout(4000);
    waited = Date.now() - tStart;
    cardsAfter = await page.locator('[data-testid="cover-letter-card"]').count();
    if (cardsAfter > cardsBefore) break;
  }
  const wallClockMs = Date.now() - tStart;
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(SHOTS, "item3b-02-after-run.png"), fullPage: false });
  await page.screenshot({ path: path.join(SHOTS, "item3b-03-after-run-full.png"), fullPage: true });

  const firstCardText = cardsAfter > 0
    ? await page.locator('[data-testid="cover-letter-card"]').first().innerText()
    : null;
  const bodyText = await page.locator("body").innerText();

  const result = {
    capturedAt: new Date().toISOString(),
    startedAtIso,
    base: BASE,
    targetJob: target,
    cardsBefore,
    cardsAfter,
    wallClockMs,
    firstCardText,
    unavailableOnPage: (bodyText.match(/Unavailable/g) || []).length,
    consoleErrors,
    pageErrors,
  };
  fs.writeFileSync(path.join(OUT, "item3b-degrade-run-ui.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ target, cardsBefore, cardsAfter, wallClockMs, consoleErrors: consoleErrors.length, firstCardText: (firstCardText || "").slice(0, 700) }, null, 2));
  await browser.close();
})().catch((e) => {
  fs.writeFileSync(path.join(OUT, "item3b-degrade-run-ui.ERROR.txt"), String(e && e.stack ? e.stack : e));
  console.error("FAILED:", e);
  process.exit(1);
});
