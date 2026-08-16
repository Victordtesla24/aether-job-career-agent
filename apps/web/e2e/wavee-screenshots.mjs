// Wave E evidence: post-wipe empty-dashboard screenshots against PROD.
// Reads LOGIN_EMAIL/LOGIN_PASSWORD from env (never printed). One-off script; not a test.
import { chromium } from "@playwright/test";

const BASE = "https://5cb5f0620.abacusai.cloud";
const OUT = process.env.OUT_DIR;
const email = process.env.LOGIN_EMAIL;
const password = process.env.LOGIN_PASSWORD;
if (!OUT || !email || !password) { console.error("missing env"); process.exit(2); }

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
await page.fill('input[name="email"]', email);
await page.fill('input[type="password"]', password);
await Promise.all([
  page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 30000 }),
  page.click('button[type="submit"]'),
]);
console.log("logged in ->", page.url());

const shots = [
  ["/dashboard", "dashboard"],
  ["/dashboard/jobs", "jobs"],
  ["/dashboard/applications", "applications"],
  ["/dashboard/agents", "agents"],
  ["/dashboard/stories", "stories"],
];
for (const [path, name] of shots) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/wave-e-${name}.png`, fullPage: false });
  console.log("shot", name, page.url());
}
await browser.close();
