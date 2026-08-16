// R1.1 evidence: desktop admin metric/dashboard surfaces render only real DB-sourced, honest data.
// Reads LOGIN_EMAIL/LOGIN_PASSWORD from env (never printed). One-off script; not a test.
import { chromium } from "@playwright/test";
const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = process.env.OUT_DIR;
const email = process.env.LOGIN_EMAIL;
const password = process.env.LOGIN_PASSWORD;
if (!OUT || !email || !password) { console.error("missing env"); process.exit(2); }
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
page.on("pageerror", (e) => consoleErrors.push("PAGEERROR: " + e.message));
await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
await page.fill('input[name="email"]', email);
await page.fill('input[type="password"]', password);
await Promise.all([
  page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 30000 }),
  page.click('button[type="submit"]'),
]);
console.log("logged in ->", page.url());
const shots = [
  ["/admin", "admin-overview"],
  ["/admin/health", "admin-health"],
  ["/admin/subscriptions", "admin-subscriptions"],
  ["/admin/spend", "admin-spend"],
  ["/admin/audit-log", "admin-audit-log"],
  ["/admin/billing", "admin-billing"],
  ["/admin/sales-agent", "admin-sales-agent"],
];
for (const [path, name] of shots) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `${OUT}/r1_1-${name}.png`, fullPage: true });
  console.log("shot", name, "->", page.url());
}
await browser.close();
import { writeFileSync } from "fs";
writeFileSync(`${OUT}/console-errors.txt`, consoleErrors.length ? consoleErrors.join("\n") : "NONE — 0 browser console errors across all admin surfaces\n");
console.log("console errors:", consoleErrors.length);
