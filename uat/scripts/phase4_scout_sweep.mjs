import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const target = 'https://5cb5f0620.abacusai.cloud';
const out = path.join(root, 'uat/reports/evidence/phase4');
const screenshotDir = path.join(out, 'screenshots');
fs.mkdirSync(screenshotDir, { recursive: true });

function envValue(key) {
  const line = fs.readFileSync(path.join(root, '.env'), 'utf8').split(/\r?\n/).find(x => x.startsWith(`${key}=`));
  return line ? line.slice(key.length + 1).replace(/^['"]|['"]$/g, '') : '';
}
const email = envValue('LOGIN_EMAIL') || envValue('AETHER_CRON_EMAIL');
const password = envValue('LOGIN_PASSWORD') || envValue('AETHER_CRON_PASSWORD');
if (!email || !password) throw new Error('Required production login credential is unavailable');

const routes = ['interviews', 'networking', 'offers', 'analytics'];
const run = { target, timestamp: new Date().toISOString(), auth: {}, screens: {} };
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const authPage = await context.newPage();
const authConsole = [];
authPage.on('console', m => authConsole.push({ type: m.type(), text: m.text() }));
authPage.on('requestfailed', r => authConsole.push({ type: 'requestfailed', url: r.url(), failure: r.failure()?.errorText || 'unknown' }));
await authPage.goto(`${target}/login`, { waitUntil: 'networkidle', timeout: 60000 });
await authPage.getByLabel(/email or username/i).fill(email);
await authPage.getByLabel(/^password$/i).fill(password);
await Promise.all([authPage.waitForTimeout(1000), authPage.getByRole('button', { name: /^sign in$/i }).click()]);
await authPage.waitForLoadState('networkidle').catch(() => {});
run.auth = { final_url: authPage.url(), signed_in: authPage.url().includes('/dashboard'), console: authConsole };
if (!run.auth.signed_in) throw new Error(`Production login failed; landed at ${authPage.url()}`);

for (const route of routes) {
  const page = await context.newPage();
  const messages = [], requests = [], interactions = [];
  page.on('console', m => messages.push({ type: m.type(), text: m.text(), location: m.location() }));
  page.on('requestfailed', r => requests.push({ type: 'requestfailed', url: r.url(), method: r.method(), failure: r.failure()?.errorText || 'unknown' }));
  page.on('response', r => { if (r.status() >= 400) requests.push({ type: 'http_error', url: r.url(), method: r.request().method(), status: r.status() }); });
  await page.goto(`${target}/dashboard/${route}`, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1200);
  const initialUrl = page.url();
  const bodyBefore = await page.locator('body').innerText();
  const controls = await page.locator('button, [role="button"], input[type="submit"], a[href]').evaluateAll(els => els.map((e, i) => ({ i, tag: e.tagName, text: (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim(), href: e.getAttribute('href'), disabled: e.disabled || e.getAttribute('aria-disabled') === 'true' })).filter(x => x.text || x.tag === 'INPUT'));
  // Click buttons only: avoid sidebar navigation and destructive links. Record outcome and continue after transient UI.
  const buttons = page.locator('button, [role="button"], input[type="submit"]');
  const count = await buttons.count();
  for (let i = 0; i < count; i++) {
    const el = buttons.nth(i);
    const label = await el.innerText().catch(() => '');
    const disabled = await el.isDisabled().catch(() => true);
    if (disabled) { interactions.push({ i, label, outcome: 'disabled' }); continue; }
    const lower = label.toLowerCase();
    if (/delete|remove|send|submit|save|schedule|add offer|add contact|confirm/.test(lower)) {
      interactions.push({ i, label, outcome: 'not_submitted_production_mutation_requires_form_data' }); continue;
    }
    try {
      await el.click({ timeout: 5000 });
      await page.waitForTimeout(350);
      interactions.push({ i, label, outcome: 'clicked', url_after: page.url() });
      if (page.url() !== initialUrl) { await page.goBack({ waitUntil: 'networkidle', timeout: 30000 }).catch(() => {}); }
    } catch (e) { interactions.push({ i, label, outcome: 'click_error', error: String(e).slice(0,300) }); }
  }
  const textAfter = await page.locator('body').innerText().catch(() => '');
  const screenshot = path.join(screenshotDir, `${route}__full__${new Date().toISOString().replace(/[:.]/g,'-')}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  const dom = await page.evaluate(() => ({
    url: location.href, title: document.title, text: document.body.innerText,
    forms: [...document.forms].map((f,i) => ({ i, action: f.action, method: f.method, fields: [...f.elements].map(e => ({ name:e.name, type:e.type, required:e.required, value: e.type === 'password' ? '[redacted]' : e.value })) })),
    buttons: [...document.querySelectorAll('button')].map((e,i) => ({i, text:e.innerText.trim(), disabled:e.disabled})),
    placeholders: [...document.body.innerText.matchAll(/.{0,40}(?:Lorem|TODO|Sample|Test data|Demo|example\.com).{0,40}/gi)].map(x=>x[0])
  }));
  run.screens[route] = { initial_url: initialUrl, screenshot, controls, interactions, body_changed: bodyBefore !== textAfter, console: messages, failed_requests: requests, dom };
  await page.close();
}
await browser.close();
fs.writeFileSync(path.join(out, 'scout-interviews-networking-offers-analytics-raw.json'), JSON.stringify(run, null, 2));
console.log(JSON.stringify({ auth: run.auth, results: Object.fromEntries(Object.entries(run.screens).map(([k,v]) => [k, { screenshot:v.screenshot, console:v.console.length, failed:v.failed_requests.length, interactions:v.interactions.length, url:v.initial_url }])) }, null, 2));
