/**
 * PROD-VERIFY-5A item 3 (completeness) — the third API-suppressed job
 * ("Product Manager - Marketplace", location "Remote") is not on the default
 * Australia market tab. Confirm its hint renders on the International tab, so
 * the W-25 hint is complete rather than missing for that job.
 */
import pw from "/home/ubuntu/github_repos/aether-job-career-agent/node_modules/.pnpm/@playwright+test@1.61.1/node_modules/@playwright/test/index.js";
const { chromium } = pw;
import fs from "node:fs";
import path from "node:path";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/prod-verify-5a";
const SHOTS = path.join(OUT, "screens");
const TARGET = "Product Manager - Marketplace";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1300 } })).newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"], input[type="email"], input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/dashboard/, { timeout: 60000 });
  await page.goto(`${BASE}/dashboard/jobs`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(13000);

  await page.getByText("International", { exact: false }).first().click();
  await page.waitForTimeout(6000);
  await page.screenshot({ path: path.join(SHOTS, "item3c-intl-tab.png"), fullPage: true });

  const cards = page.locator('[data-testid="job-card"]');
  const n = await cards.count();
  let found = null;
  for (let i = 0; i < n; i++) {
    const text = (await cards.nth(i).innerText()).trim();
    if (!text.includes(TARGET)) continue;
    const hint = cards.nth(i).locator('[data-testid="autopilot-suppressed-hint"]');
    found = {
      index: i,
      hintPresent: (await hint.count()) > 0,
      hintText: (await hint.count()) > 0 ? (await hint.first().innerText()).trim() : null,
    };
    break;
  }
  const out = { capturedAt: new Date().toISOString(), tab: "International",
    cardsOnTab: n, target: TARGET, found, consoleErrors };
  fs.writeFileSync(path.join(OUT, "89-item3c-intl-tab.json"), JSON.stringify(out, null, 2));
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error("SCRIPT ERROR", e); process.exit(1); });
