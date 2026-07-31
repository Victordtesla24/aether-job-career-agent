/**
 * PROD-VERIFY-5A items 3 + 4 against LIVE production.
 *
 * Item 3 — /dashboard/jobs must render the W-25 autopilot-suppression hint on the
 * card (and detail panel) of every job the API reports as suppressed, and NOTHING
 * on a clean job. The suppressed/clean ids are supplied from the API payload
 * captured in 70-jobs-suppression-state.json so the DOM is checked against the
 * backend's own answer, never against a guess.
 *
 * Item 4 — full sidebar sweep of all 13 NAV_ITEMS routes: console errors,
 * pageerrors, failed requests, non-2xx/3xx /api responses, and the buildId served
 * on each route.
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-5a";
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const ROUTES = [
  "/dashboard", "/dashboard/jobs", "/dashboard/resume", "/dashboard/cover-letters",
  "/dashboard/stories", "/dashboard/applications", "/dashboard/interviews",
  "/dashboard/networking", "/dashboard/email", "/dashboard/agents",
  "/dashboard/analytics", "/dashboard/offers", "/dashboard/settings",
];

const jobsPayload = JSON.parse(
  fs.readFileSync(path.join(OUT, "70-jobs-suppression-state.json"), "utf8")
);
const jobsArr = Array.isArray(jobsPayload) ? jobsPayload : jobsPayload.jobs;
const suppressedIds = jobsArr.filter((j) => j.autopilotSuppressedUntil).map((j) => j.id);
const cleanIds = jobsArr.filter((j) => !j.autopilotSuppressedUntil).map((j) => j.id);

const consoleErrors = [];
const pageErrors = [];
const failedRequests = [];
const apiNon2xx = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
  const page = await ctx.newPage();
  let current = "";
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push({ route: current, text: m.text() }); });
  page.on("pageerror", (e) => pageErrors.push({ route: current, text: String(e) }));
  page.on("requestfailed", (r) => failedRequests.push({ route: current, url: r.url(), failure: r.failure()?.errorText }));
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 400) {
      apiNon2xx.push({ route: current, url: r.url(), status: r.status() });
    }
  });

  current = "/login";
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', (process.env.LOGIN_EMAIL ?? (() => { throw new Error("LOGIN_EMAIL must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.fill('input[type="password"]', (process.env.LOGIN_PASSWORD ?? (() => { throw new Error("LOGIN_PASSWORD must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });

  // ---------- item 3: suppression hint ----------
  current = "/dashboard/jobs";
  await page.goto(`${BASE}/dashboard/jobs`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(12000);
  await page.screenshot({ path: path.join(SHOTS, "item3-jobs-full.png"), fullPage: true });

  const hintNodes = page.locator('[data-testid="autopilot-suppressed-hint"]');
  const hintCount = await hintNodes.count();
  const hintTexts = [];
  for (let i = 0; i < hintCount; i++) hintTexts.push((await hintNodes.nth(i).innerText()).trim());
  const detail = page.locator('[data-testid="autopilot-suppressed-hint-detail"]');
  const detailCount = await detail.count();
  const detailText = detailCount > 0 ? (await detail.first().innerText()).trim() : null;

  // per-job check: does the card whose title matches a suppressed job carry a hint?
  const perJob = {};
  for (const j of jobsArr) {
    const titleLoc = page.getByText(j.title, { exact: false }).first();
    if ((await titleLoc.count()) === 0) { perJob[j.id] = { title: j.title, visible: false }; continue; }
    // walk up to the nearest card container and look for the hint inside it
    const inCard = await titleLoc.evaluate((el) => {
      let n = el;
      for (let i = 0; i < 12 && n; i++) {
        if (n.querySelector && n.querySelector('[data-testid="autopilot-suppressed-hint"]')) return true;
        n = n.parentElement;
      }
      return false;
    }).catch(() => null);
    perJob[j.id] = {
      title: j.title,
      visible: true,
      apiSuppressedUntil: j.autopilotSuppressedUntil || null,
      hintInCard: inCard,
      verdict: inCard === Boolean(j.autopilotSuppressedUntil) ? "PASS" : "FAIL",
    };
  }
  if (hintCount > 0) {
    await hintNodes.first().screenshot({ path: path.join(SHOTS, "item3-hint-closeup.png") }).catch(() => {});
  }

  // ---------- item 4: sidebar sweep ----------
  const perRoute = {};
  for (const route of ROUTES) {
    current = route;
    const before = { c: consoleErrors.length, p: pageErrors.length, a: apiNon2xx.length };
    const resp = await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(8000);
    const html = await page.content();
    const m = html.match(/"buildId":\s*"([^"]+)"/) || html.match(/buildId\\?":\\?"([^"\\]+)/);
    const bodyText = await page.locator("body").innerText();
    perRoute[route] = {
      httpStatus: resp ? resp.status() : null,
      buildId: m ? m[1] : null,
      bodyChars: bodyText.length,
      newConsoleErrors: consoleErrors.length - before.c,
      newPageErrors: pageErrors.length - before.p,
      newApiNon2xx: apiNon2xx.length - before.a,
      crashMarkers: /Application error|Unhandled Runtime Error|Internal Server Error|something went wrong/i.test(bodyText),
    };
    await page.screenshot({
      path: path.join(SHOTS, `item4${route.replace(/\//g, "_")}.png`), fullPage: true,
    });
  }

  const report = {
    capturedAt: new Date().toISOString(), base: BASE,
    item3: {
      apiSuppressedIds: suppressedIds, apiCleanCount: cleanIds.length,
      hintNodesRendered: hintCount, hintTexts, detailHintRendered: detailCount, detailText, perJob,
    },
    item4: { perRoute, consoleErrors, pageErrors, failedRequests, apiNon2xx },
  };
  fs.writeFileSync(path.join(OUT, "82-item3-item4-sweep.json"), JSON.stringify(report, null, 2));

  console.log("--- ITEM 3 ---");
  console.log("api suppressed:", suppressedIds.length, "| hint nodes in DOM:", hintCount, "| detail hint:", detailCount);
  hintTexts.forEach((t) => console.log("   hint:", t));
  console.log("   detail:", detailText);
  const fails = Object.entries(perJob).filter(([, v]) => v.verdict === "FAIL");
  console.log("   per-job mismatches:", fails.length, JSON.stringify(fails.slice(0, 6)));
  console.log("--- ITEM 4 ---");
  for (const [r, v] of Object.entries(perRoute)) {
    console.log(`${r} http=${v.httpStatus} build=${v.buildId} chars=${v.bodyChars} cErr=${v.newConsoleErrors} pErr=${v.newPageErrors} api4xx=${v.newApiNon2xx} crash=${v.crashMarkers}`);
  }
  console.log("TOTAL consoleErrors", consoleErrors.length, "pageErrors", pageErrors.length,
    "failedRequests", failedRequests.length, "apiNon2xx", apiNon2xx.length);
  console.log("apiNon2xx detail:", JSON.stringify(apiNon2xx, null, 1));
  console.log("consoleErrors detail:", JSON.stringify(consoleErrors, null, 1));
  await browser.close();
})().catch((e) => { console.error("SCRIPT ERROR", e); process.exit(1); });
