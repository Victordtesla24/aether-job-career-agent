/** Item 5 — confirm the submitted application renders as submitted in the UI. Read-only. */
import { chromium } from "@playwright/test";
import fs from "node:fs";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-final-2026-07-29";

(async () => {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill("#login-identifier", "admin");
  await page.fill("#login-password", "admin123");
  await Promise.all([page.waitForURL(/\/dashboard/, { timeout: 60000 }).catch(() => {}), page.click('button[type="submit"]')]);
  await page.goto(`${BASE}/dashboard/applications`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(9000);

  const res = { capturedAt: new Date().toISOString() };
  res.boardText = await page.evaluate(() => (document.querySelector("main") || document.body).innerText.replace(/\s+/g, " "));
  res.foundOnBoard = res.boardText.includes("MUSEUM OF ICE CREAM");

  // switch to the Applied view
  const applied = page.locator('button:has-text("Applied")').first();
  if (await applied.count()) { await applied.click(); await page.waitForTimeout(6000); }
  res.appliedViewText = await page.evaluate(() => (document.querySelector("main") || document.body).innerText.replace(/\s+/g, " "));
  const i = res.appliedViewText.indexOf("MUSEUM OF ICE CREAM");
  res.foundInAppliedView = i >= 0;
  res.appliedContext = i >= 0 ? res.appliedViewText.slice(Math.max(0, i - 300), i + 300) : null;
  await page.screenshot({ path: `${OUT}/screens/item5-applied-view.png`, fullPage: false });

  fs.writeFileSync(`${OUT}/item5-ui-verification.json`, JSON.stringify(res, null, 2));
  console.log(JSON.stringify({ foundOnBoard: res.foundOnBoard, foundInAppliedView: res.foundInAppliedView, ctx: res.appliedContext }, null, 1));
  await browser.close();
})().catch((e) => { console.error("ITEM5-UI FAILED:", e); process.exit(1); });
