/**
 * Follow-up browser checks: warm email time-to-content (item 4), buildId in an
 * authenticated app shell (item 1), submitted-card render (item 5), sparse-screen
 * honesty re-check (item 1). Read-only.
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-final-2026-07-29";
const SHOTS = path.join(OUT, "screens");
const out = { capturedAt: new Date().toISOString(), console: [], pageerror: [], requestfailed: [] };

(async () => {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  let current = "login";
  page.on("console", (m) => { if (m.type() === "error") out.console.push({ current, text: m.text().slice(0, 300) }); });
  page.on("pageerror", (e) => out.pageerror.push({ current, message: String(e.message).slice(0, 300) }));
  page.on("requestfailed", (r) => out.requestfailed.push({ current, url: r.url(), failure: r.failure()?.errorText }));

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill("#login-identifier", "admin");
  await page.fill("#login-password", "admin123");
  await Promise.all([page.waitForURL(/\/dashboard/, { timeout: 60000 }).catch(() => {}), page.click('button[type="submit"]')]);
  await page.waitForTimeout(2500);

  // buildId from an authenticated route's RSC payload
  out.buildId = await page.evaluate(() => {
    const html = document.documentElement.outerHTML;
    const m = html.match(/\\?"buildId\\?":\\?"([A-Za-z0-9_-]+)\\?"/);
    return m ? m[1] : null;
  });
  out.buildIdDisk = fs.readFileSync("/home/ubuntu/github_repos/aether-job-career-agent/apps/web/.next/BUILD_ID", "utf8").trim();
  out.buildIdMatch = out.buildId === out.buildIdDisk;

  // ---- item 4: /dashboard/email time-to-content, three warm loads ----
  out.emailLoads = [];
  for (let i = 0; i < 3; i++) {
    current = `email#${i + 1}`;
    const t0 = Date.now();
    await page.goto(`${BASE}/dashboard/email`, { waitUntil: "domcontentloaded", timeout: 90000 });
    let ttc = null;
    try {
      await page.waitForFunction(() => {
        const m = document.querySelector("main") || document.body;
        return (m.innerText || "").replace(/\s+/g, " ").trim().length > 2000;
      }, { timeout: 90000 });
      ttc = Date.now() - t0;
    } catch { ttc = null; }
    out.emailLoads.push({ attempt: i + 1, timeToContentMs: ttc, at: new Date().toISOString() });
    await page.waitForTimeout(1500);
  }
  await page.screenshot({ path: path.join(SHOTS, "item4-email-warm.png") });

  // ---- item 5: the submitted card on the board ----
  current = "applications";
  await page.goto(`${BASE}/dashboard/applications`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(7000);
  out.item5Board = await page.evaluate(() => {
    const t = (document.querySelector("main") || document.body).innerText.replace(/\s+/g, " ");
    const i = t.indexOf("MUSEUM OF ICE CREAM");
    return { found: i >= 0, context: i >= 0 ? t.slice(Math.max(0, i - 260), i + 260) : null };
  });
  await page.screenshot({ path: path.join(SHOTS, "item5-applications-board.png"), fullPage: true });

  // ---- sparse screens honesty re-check ----
  out.sparseScreens = {};
  for (const r of ["/dashboard/interviews", "/dashboard/offers", "/dashboard/networking", "/dashboard/approvals"]) {
    current = r;
    await page.goto(`${BASE}${r}`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(6000);
    out.sparseScreens[r] = await page.evaluate(() => {
      const m = document.querySelector("main") || document.body;
      const txt = (m.innerText || "").replace(/\s+/g, " ").trim();
      return {
        textLen: txt.length,
        text: txt.slice(0, 600),
        buttons: [...m.querySelectorAll("button")].map((b) => b.innerText.trim()).filter(Boolean).slice(0, 12),
        hasSkeleton: !!m.querySelector("[class*='animate-pulse'],[class*='skeleton']"),
      };
    });
    await page.screenshot({ path: path.join(SHOTS, `sparse${r.replace(/\//g, "-")}.png`) });
  }

  fs.writeFileSync(path.join(OUT, "item1b-followup-browser.json"), JSON.stringify(out, null, 2));
  console.log(JSON.stringify({ buildIdMatch: out.buildIdMatch, emailLoads: out.emailLoads, consoleErrors: out.console.length, pageErrors: out.pageerror.length }));
  await browser.close();
})().catch((e) => { console.error("FOLLOWUP FAILED:", e); process.exit(1); });
