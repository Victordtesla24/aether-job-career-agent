/**
 * Independent QA closure sweep — production https://5cb5f0620.abacusai.cloud
 * Covers recipe items 1 (external sweep), 4 (email TTC), 6 (settings), 7 (analytics tooltip).
 * Read-only: navigates and reads DOM. The ONE mutation (item 5 submit) is done separately.
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-final-2026-07-29";
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const ROUTES = [
  ["/dashboard", "dashboard"],
  ["/dashboard/jobs", "jobs"],
  ["/dashboard/applications", "applications"],
  ["/dashboard/resume", "resume"],
  ["/dashboard/cover-letters", "cover-letters"],
  ["/dashboard/email", "email"],
  ["/dashboard/interviews", "interviews"],
  ["/dashboard/offers", "offers"],
  ["/dashboard/networking", "networking"],
  ["/dashboard/stories", "stories"],
  ["/dashboard/analytics", "analytics"],
  ["/dashboard/agents", "agents"],
  ["/dashboard/approvals", "approvals"],
  ["/dashboard/settings", "settings"],
];

const report = {
  capturedAt: new Date().toISOString(),
  base: BASE,
  buildId: { served: null, disk: fs.readFileSync("/home/ubuntu/github_repos/aether-job-career-agent/apps/web/.next/BUILD_ID", "utf8").trim(), match: null },
  routes: [],
  totals: { consoleErrors: 0, pageErrors: 0, requestFailed: 0, badStaticChunks: 0 },
  item4_emailTimeToContent: null,
  item6_settings: null,
  item7_analyticsTooltip: null,
};

const sink = { console: [], pageerror: [], requestfailed: [], responses: [] };
let current = "boot";

function attach(page) {
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") {
      sink.console.push({ route: current, type: m.type(), text: m.text().slice(0, 500), loc: m.location() });
    }
  });
  page.on("pageerror", (e) => sink.pageerror.push({ route: current, message: String(e.message).slice(0, 500) }));
  page.on("requestfailed", (r) =>
    sink.requestfailed.push({ route: current, url: r.url(), failure: r.failure()?.errorText || "unknown", type: r.resourceType() })
  );
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/_next/static/") || u.includes("/api/") || r.status() >= 400) {
      sink.responses.push({ route: current, url: u, status: r.status(), type: r.request().resourceType() });
    }
  });
}

async function textLen(page) {
  return page.evaluate(() => {
    const m = document.querySelector("main") || document.body;
    return (m.innerText || "").replace(/\s+/g, " ").trim().length;
  });
}

(async () => {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, ignoreHTTPSErrors: false });
  const page = await ctx.newPage();
  attach(page);

  // ---- login ----
  current = "/login";
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 60000 });
  report.buildId.served = await page.evaluate(() => {
    const s = [...document.scripts].map((x) => x.textContent || "").join("");
    const m = s.match(/"buildId":"([^"]+)"/);
    return m ? m[1] : null;
  });
  report.buildId.match = report.buildId.served === report.buildId.disk;
  await page.fill("#login-identifier", "admin");
  await page.fill("#login-password", "admin123");
  await Promise.all([
    page.waitForURL(/\/dashboard/, { timeout: 60000 }).catch(() => {}),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(SHOTS, "00-after-login.png"), fullPage: false });
  report.loginLandedOn = page.url();

  // ---- route sweep ----
  for (const [route, name] of ROUTES) {
    current = route;
    const t0 = Date.now();
    const before = { c: sink.console.length, p: sink.pageerror.length, f: sink.requestfailed.length };
    let navOk = true, navErr = null;
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded", timeout: 60000 });
    } catch (e) {
      navOk = false; navErr = String(e.message).slice(0, 200);
    }
    // wait for real content (not just skeleton)
    let ttc = null;
    try {
      await page.waitForFunction(
        () => {
          const m = document.querySelector("main") || document.body;
          return (m.innerText || "").replace(/\s+/g, " ").trim().length > 400;
        },
        { timeout: 45000 }
      );
      ttc = Date.now() - t0;
    } catch { ttc = null; }
    await page.waitForTimeout(2500);
    const len = await textLen(page);
    const head = await page.evaluate(() => {
      const m = document.querySelector("main") || document.body;
      return (m.innerText || "").replace(/\s+/g, " ").trim().slice(0, 260);
    });
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });
    report.routes.push({
      route, name, navOk, navErr, url: page.url(), timeToContentMs: ttc, textLen: len, textHead: head,
      newConsole: sink.console.length - before.c,
      newPageErrors: sink.pageerror.length - before.p,
      newRequestFailed: sink.requestfailed.length - before.f,
    });
    if (route === "/dashboard/email") report.item4_emailTimeToContent = ttc;
  }

  // ---- item 7: analytics total-applications tooltip ----
  current = "/dashboard/analytics";
  await page.goto(`${BASE}/dashboard/analytics`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(6000);
  report.item7_analyticsTooltip = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll("[title]").forEach((el) => {
      const t = el.getAttribute("title") || "";
      if (/application/i.test(t)) out.push({ tag: el.tagName, title: t, text: (el.innerText || "").replace(/\s+/g, " ").slice(0, 120) });
    });
    return out;
  });
  await page.screenshot({ path: path.join(SHOTS, "item7-analytics.png"), fullPage: false });

  // ---- item 6: settings privacy panel + agent hints ----
  current = "/dashboard/settings";
  await page.goto(`${BASE}/dashboard/settings`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(5000);
  const s6 = { privacy: {}, hints: {} };
  await page.click('[data-testid="settings-nav-privacy"]');
  await page.waitForTimeout(1500);
  s6.privacy.panelVisible = await page.locator('[data-testid="settings-privacy"]').isVisible().catch(() => false);
  s6.privacy.panelText = await page.locator('[data-testid="settings-privacy"]').innerText().catch(() => null);
  s6.privacy.profilePanelAlsoVisible = await page.locator('[data-testid="settings-email"]').isVisible().catch(() => false);
  await page.screenshot({ path: path.join(SHOTS, "item6-settings-privacy.png"), fullPage: false });
  // policy/terms links
  const links = await page.evaluate(() => {
    const p = document.querySelector('[data-testid="settings-privacy"]');
    return p ? [...p.querySelectorAll("a")].map((a) => ({ href: a.getAttribute("href"), text: a.innerText.trim() })) : [];
  });
  s6.privacy.links = links;
  s6.privacy.linkChecks = [];
  for (const l of links) {
    if (!l.href || !l.href.startsWith("/")) continue;
    const r = await ctx.request.get(`${BASE}${l.href}`);
    let body = "";
    try { body = (await r.text()).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(); } catch {}
    s6.privacy.linkChecks.push({ href: l.href, status: r.status(), textLen: body.length, head: body.slice(0, 140) });
  }
  // agent config hints
  await page.click('[data-testid="settings-nav-agents"]');
  await page.waitForTimeout(1500);
  for (const t of ["hint-autoapply", "hint-approvalgate", "hint-matchthreshold"]) {
    s6.hints[t] = {
      visible: await page.locator(`[data-testid="${t}"]`).isVisible().catch(() => false),
      text: await page.locator(`[data-testid="${t}"]`).innerText().catch(() => null),
    };
  }
  await page.screenshot({ path: path.join(SHOTS, "item6-settings-agents.png"), fullPage: false });
  report.item6_settings = s6;

  // ---- totals ----
  report.consoleMessages = sink.console;
  report.pageErrors = sink.pageerror;
  report.requestFailures = sink.requestfailed;
  const statics = sink.responses.filter((r) => r.url.includes("/_next/static/"));
  report.staticChunks = { total: statics.length, nonOk: statics.filter((r) => r.status !== 200 && r.status !== 304) };
  report.apiNon2xx = sink.responses.filter((r) => r.url.includes("/api/") && r.status >= 400);
  report.totals = {
    consoleErrors: sink.console.filter((c) => c.type === "error").length,
    consoleWarnings: sink.console.filter((c) => c.type === "warning").length,
    pageErrors: sink.pageerror.length,
    requestFailed: sink.requestfailed.length,
    badStaticChunks: report.staticChunks.nonOk.length,
    apiNon2xx: report.apiNon2xx.length,
  };

  fs.writeFileSync(path.join(OUT, "item1-external-sweep.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report.totals));
  console.log("buildId", JSON.stringify(report.buildId));
  await browser.close();
})().catch((e) => {
  fs.writeFileSync(path.join(OUT, "item1-external-sweep-ERROR.txt"), String(e.stack || e));
  console.error("SWEEP FAILED:", e);
  process.exit(1);
});
