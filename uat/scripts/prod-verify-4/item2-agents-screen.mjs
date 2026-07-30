/**
 * QA #4 item 2 — /dashboard/agents must render degraded (letterless) coverLetter
 * runs as "Unavailable"/"N/A", never as a success, and must disclose the degraded
 * count in its success-rate figures.
 * Target: LIVE production https://5cb5f0620.abacusai.cloud (external URL only).
 * Read-only: navigates and reads DOM. No mutation.
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-4";
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const consoleErrors = [];
const pageErrors = [];
const failedRequests = [];
const apiResponses = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  const page = await ctx.newPage();

  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push({ url: page.url(), text: m.text() });
  });
  page.on("pageerror", (e) => pageErrors.push({ url: page.url(), text: String(e) }));
  page.on("requestfailed", (r) =>
    failedRequests.push({ url: r.url(), failure: r.failure()?.errorText })
  );
  page.on("response", (r) => {
    if (r.url().includes("/api/")) apiResponses.push({ url: r.url(), status: r.status() });
  });

  // --- real UI login ---
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });
  const loginUrl = page.url();

  // --- /dashboard/agents ---
  await page.goto(`${BASE}/dashboard/agents`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);
  await page.screenshot({ path: path.join(SHOTS, "item2-agents-top.png"), fullPage: false });
  await page.screenshot({ path: path.join(SHOTS, "item2-agents-full.png"), fullPage: true });

  const grab = async (tid) => {
    const el = page.locator(`[data-testid="${tid}"]`);
    if ((await el.count()) === 0) return null;
    return (await el.first().innerText()).replace(/\n{3,}/g, "\n\n");
  };

  const statSuccess = await grab("stat-success");
  const perf = await grab("performance-metrics");
  const taskQueue = await grab("task-queue");
  const errorLog = await grab("error-log");
  const runsTable = await grab("agent-runs-table");
  const agentStats = await grab("agent-stats");

  const bodyText = await page.locator("body").innerText();
  const count = (re) => (bodyText.match(re) || []).length;

  const badgeCounts = {
    Unavailable: count(/\bUnavailable\b/g),
    "N/A": count(/\bN\/A\b/g),
    degraded: count(/\bdegraded\b/gi),
    OK: count(/\bOK\b/g),
    Failed: count(/\bFailed\b/g),
  };

  // live /agents/stats payload as the browser saw it
  const statsPayload = await page.evaluate(async () => {
    try {
      const r = await fetch("/api/agents/stats", { credentials: "include" });
      return { status: r.status, body: await r.json() };
    } catch (e) {
      return { error: String(e) };
    }
  });
  const runsPayload = await page.evaluate(async () => {
    try {
      const r = await fetch("/api/agents/runs?limit=50", { credentials: "include" });
      const j = await r.json();
      const rows = Array.isArray(j) ? j : j.runs || j.items || [];
      return {
        status: r.status,
        n: rows.length,
        rows: rows.map((x) => ({
          id: x.id,
          agentName: x.agentName,
          status: x.status,
          createdAt: x.createdAt,
          degraded: (x.output || {}).coverLetterUnavailable === true,
          letterId: (x.output || {}).cover_letter_id ?? (x.output || {}).coverLetterId ?? null,
          model: (x.output || {}).model ?? null,
          costUsd: (x.output || {}).costUsd ?? null,
          tokensIn: (x.output || {}).tokensIn ?? null,
          tokensOut: (x.output || {}).tokensOut ?? null,
        })),
      };
    } catch (e) {
      return { error: String(e) };
    }
  });

  const result = {
    capturedAt: new Date().toISOString(),
    base: BASE,
    loginUrl,
    panels: { statSuccess, agentStats, perf, taskQueue, errorLog, runsTable },
    badgeCounts,
    statsPayload,
    runsPayload,
    consoleErrors,
    pageErrors,
    failedRequests,
    apiNon2xx: apiResponses.filter((r) => r.status >= 300),
    apiResponsesObserved: apiResponses.length,
  };
  fs.writeFileSync(path.join(OUT, "item2-agents-screen.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ badgeCounts, statSuccess, perf: (perf || "").slice(0, 400), consoleErrors: consoleErrors.length, pageErrors: pageErrors.length }, null, 2));

  await browser.close();
})().catch((e) => {
  fs.writeFileSync(path.join(OUT, "item2-agents-screen.ERROR.txt"), String(e && e.stack ? e.stack : e));
  console.error("FAILED:", e);
  process.exit(1);
});
