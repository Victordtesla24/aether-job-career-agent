/**
 * PROD-VERIFY-5A item 3 (precise re-check).
 *
 * The first pass walked up N parents from a title text node to look for the hint,
 * which reaches a container holding many cards and therefore reports false
 * positives. This pass scopes strictly to each `[data-testid="job-card"]` article
 * and compares, card by card, the rendered hint against the API's own
 * `autopilotSuppressedUntil` for the job with that title. It also clicks a
 * suppressed card to assert the detail-panel hint, and clicks a clean card to
 * assert the detail panel shows nothing.
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-5a";
const SHOTS = path.join(OUT, "screens");

const payload = JSON.parse(fs.readFileSync(path.join(OUT, "70-jobs-suppression-state.json"), "utf8"));
const jobsArr = Array.isArray(payload) ? payload : payload.jobs;
const byTitle = new Map(jobsArr.map((j) => [j.title.trim(), j]));

const consoleErrors = [];
const pageErrors = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1300 } });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });
  await page.goto(`${BASE}/dashboard/jobs`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(13000);

  const cards = page.locator('[data-testid="job-card"]');
  const n = await cards.count();
  const rows = [];
  for (let i = 0; i < n; i++) {
    const c = cards.nth(i);
    const text = (await c.innerText()).trim();
    const hint = c.locator('[data-testid="autopilot-suppressed-hint"]');
    const hintPresent = (await hint.count()) > 0;
    const hintText = hintPresent ? (await hint.first().innerText()).trim() : null;
    // resolve which API job this card is, by exact title match on the first line
    let matchedTitle = null;
    for (const t of byTitle.keys()) if (text.includes(t)) {
      if (!matchedTitle || t.length > matchedTitle.length) matchedTitle = t;
    }
    const apiJob = matchedTitle ? byTitle.get(matchedTitle) : null;
    const apiSuppressed = apiJob ? Boolean(apiJob.autopilotSuppressedUntil) : null;
    rows.push({
      index: i, matchedTitle, apiJobId: apiJob?.id ?? null,
      apiSuppressedUntil: apiJob?.autopilotSuppressedUntil ?? null,
      hintPresent, hintText,
      verdict: apiJob == null ? "UNMATCHED" : hintPresent === apiSuppressed ? "PASS" : "FAIL",
    });
  }

  // detail-panel check: click a suppressed card, then a clean card
  const detailChecks = {};
  for (const want of [true, false]) {
    const target = rows.find((r) => r.verdict === "PASS" && r.hintPresent === want);
    if (!target) { detailChecks[want ? "suppressed" : "clean"] = "NO_CANDIDATE"; continue; }
    await cards.nth(target.index).scrollIntoViewIfNeeded();
    await cards.nth(target.index).click();
    await page.waitForTimeout(4500);
    const d = page.locator('[data-testid="autopilot-suppressed-hint-detail"]');
    detailChecks[want ? "suppressed" : "clean"] = {
      title: target.matchedTitle,
      detailHintPresent: (await d.count()) > 0,
      detailHintText: (await d.count()) > 0 ? (await d.first().innerText()).trim() : null,
      expectedPresent: want,
      verdict: ((await d.count()) > 0) === want ? "PASS" : "FAIL",
    };
    await page.screenshot({
      path: path.join(SHOTS, `item3b-detail-${want ? "suppressed" : "clean"}.png`), fullPage: true,
    });
  }

  const apiSuppressedTitles = jobsArr.filter((j) => j.autopilotSuppressedUntil).map((j) => j.title);
  const renderedTitles = rows.map((r) => r.matchedTitle);
  const report = {
    capturedAt: new Date().toISOString(),
    cardsRendered: n,
    apiSuppressedTitles,
    apiSuppressedNotRendered: apiSuppressedTitles.filter((t) => !renderedTitles.includes(t)),
    rows, detailChecks, consoleErrors, pageErrors,
  };
  fs.writeFileSync(path.join(OUT, "83-item3b-suppression-precise.json"), JSON.stringify(report, null, 2));
  console.log("cards rendered:", n);
  console.log("api suppressed titles:", apiSuppressedTitles);
  console.log("api-suppressed but NOT rendered on the board:", report.apiSuppressedNotRendered);
  for (const r of rows) {
    console.log(`  [${r.verdict}] hint=${r.hintPresent} api=${r.apiSuppressedUntil} :: ${r.matchedTitle}`);
  }
  console.log("detailChecks:", JSON.stringify(detailChecks, null, 1));
  console.log("consoleErrors", consoleErrors.length, "pageErrors", pageErrors.length);
  await browser.close();
})().catch((e) => { console.error("SCRIPT ERROR", e); process.exit(1); });
