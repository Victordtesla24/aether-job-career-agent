/** Item 7 — analytics total-applications tooltip honesty. Read-only. */
import { chromium } from "@playwright/test";
import fs from "node:fs";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-final-2026-07-29";

(async () => {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill("#login-identifier", (process.env.LOGIN_EMAIL ?? (() => { throw new Error("LOGIN_EMAIL must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await page.fill("#login-password", (process.env.LOGIN_PASSWORD ?? (() => { throw new Error("LOGIN_PASSWORD must be set — no login credential is hardcoded in this repo (BLOCKER-001)"); })()));
  await Promise.all([page.waitForURL(/\/dashboard/, { timeout: 60000 }).catch(() => {}), page.click('button[type="submit"]')]);
  await page.goto(`${BASE}/dashboard/analytics`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="metric-tooltip"]', { timeout: 60000 });
  await page.waitForTimeout(3000);

  const res = { capturedAt: new Date().toISOString(), tiles: [] };
  // Every summary tile: <dt>label</dt><dd><MetricTooltip/></dd>
  const tiles = await page.$$("dl > div");
  for (const tile of tiles) {
    const label = await tile.$eval("dt", (n) => n.innerText.trim()).catch(() => null);
    const trigger = await tile.$('[data-testid="metric-tooltip-trigger"]');
    if (!label || !trigger) continue;
    await trigger.hover();
    await page.waitForTimeout(600);
    const tip = await tile.$eval('[data-testid="metric-tooltip-popover"]', (n) => n.innerText.trim()).catch(() => null);
    const value = await tile.$eval("dd", (n) => n.innerText.trim()).catch(() => null);
    res.tiles.push({ label, value, tooltip: tip });
    await page.mouse.move(0, 0);
    await page.waitForTimeout(200);
  }
  const apps = res.tiles.find((t) => t.label === "Applications");
  res.applicationsTooltip = apps ? apps.tooltip : null;
  res.claimsDraftsExcluded = apps ? /exclud/i.test(apps.tooltip || "") : null;
  // hover the Applications tile again for the screenshot
  if (apps) {
    const t = tiles[res.tiles.findIndex((x) => x.label === "Applications")];
    const trig = await t.$('[data-testid="metric-tooltip-trigger"]');
    if (trig) { await trig.hover(); await page.waitForTimeout(700); }
  }
  await page.screenshot({ path: `${OUT}/screens/item7-applications-tooltip.png` });
  fs.writeFileSync(`${OUT}/item7-analytics-tooltip.json`, JSON.stringify(res, null, 2));
  console.log(JSON.stringify(res, null, 1));
  await browser.close();
})().catch((e) => { console.error("ITEM7 FAILED:", e); process.exit(1); });
