/**
 * QA #4 item 4 — regression sweep of key screens on LIVE production.
 * 0 console errors, 0 pageerrors, no first-party /api failure, buildId match.
 * Deliberately makes NO in-page fetch of its own (an unauthenticated fetch would
 * self-inflict a 401 console error and pollute the reading — QA4 note).
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-4";
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const ROUTES = [
  ["/dashboard", "dashboard"],
  ["/dashboard/jobs", "jobs"],
  ["/dashboard/cover-letters", "cover-letters"],
  ["/dashboard/agents", "agents"],
  ["/dashboard/applications", "applications"],
];

const consoleErrors = [];
const pageErrors = [];
const failedRequests = [];
const apiResponses = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  const page = await ctx.newPage();
  let current = "/login";
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push({ route: current, text: m.text() }); });
  page.on("pageerror", (e) => pageErrors.push({ route: current, text: String(e) }));
  page.on("requestfailed", (r) => failedRequests.push({ route: current, url: r.url(), failure: r.failure()?.errorText }));
  page.on("response", (r) => { if (r.url().includes("/api/")) apiResponses.push({ route: current, url: r.url(), status: r.status() }); });

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });

  const screens = [];
  for (const [route, name] of ROUTES) {
    current = route;
    await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(7000);
    await page.screenshot({ path: path.join(SHOTS, `item4-${name}.png`), fullPage: false });
    const bodyText = await page.locator("body").innerText();
    screens.push({
      route,
      name,
      url: page.url(),
      title: await page.title(),
      bodyChars: bodyText.length,
      first160: bodyText.slice(0, 160).replace(/\n+/g, " | "),
    });
  }

  // buildId as SERVED to this browser session
  const servedBuildId = await page.evaluate(() => {
    const s = [...document.querySelectorAll("script[src]")].map((x) => x.src);
    const m = s.map((u) => u.match(/\/_next\/static\/([^/]+)\/_(?:buildManifest|ssgManifest)/)).find(Boolean);
    return m ? m[1] : (window.__NEXT_DATA__ && window.__NEXT_DATA__.buildId) || null;
  });

  const result = {
    capturedAt: new Date().toISOString(),
    base: BASE,
    screens,
    servedBuildIdFromDom: servedBuildId,
    consoleErrors,
    pageErrors,
    failedRequests,
    apiResponsesObserved: apiResponses.length,
    apiNon2xx: apiResponses.filter((r) => r.status >= 300),
    firstPartyApiFailures: failedRequests.filter((r) => r.url.startsWith(BASE) && r.url.includes("/api/")),
    thirdPartyFailures: failedRequests.filter((r) => !r.url.startsWith(BASE)),
  };
  fs.writeFileSync(path.join(OUT, "item4-regression.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({
    screens: screens.map((s) => `${s.route} chars=${s.bodyChars}`),
    consoleErrors: consoleErrors.length,
    pageErrors: pageErrors.length,
    apiResponsesObserved: result.apiResponsesObserved,
    apiNon2xx: result.apiNon2xx,
    firstPartyApiFailures: result.firstPartyApiFailures.map((f) => f.url),
    thirdPartyFailures: result.thirdPartyFailures.map((f) => f.url),
  }, null, 2));
  await browser.close();
})().catch((e) => {
  fs.writeFileSync(path.join(OUT, "item4-regression.ERROR.txt"), String(e && e.stack ? e.stack : e));
  console.error("FAILED:", e);
  process.exit(1);
});
