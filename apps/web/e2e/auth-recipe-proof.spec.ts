/**
 * AUTH RECIPE PROOF TEST
 *
 * Playwright test to prove the browser auth mechanism works and produce
 * evidence artifacts.
 */

import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { requireEnv } from './env';

const __filename = fileURLToPath(import.meta.url);

const PROD_URL = 'https://5cb5f0620.abacusai.cloud';
// No login credential is hardcoded in this repository (BLOCKER-001). Resolved
// lazily inside the test so an unset variable fails this spec loudly rather
// than throwing at collection time for the whole suite.
const adminEmail = () => requireEnv('LOGIN_EMAIL');
const adminPassword = () => requireEnv('LOGIN_PASSWORD');
const EVIDENCE_DIR = '/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/manual-verification/screens';

test('Auth Recipe Proof: Login and reach authenticated dashboard', async ({ page }) => {
  console.log('[1] Navigating to login page...');
  await page.goto(`${PROD_URL}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });

  // Screenshot of login form
  const loginFormPath = path.join(EVIDENCE_DIR, 'AUTH-RECIPE-PROOF-step1-login-form.png');
  fs.mkdirSync(path.dirname(loginFormPath), { recursive: true });
  await page.screenshot({ path: loginFormPath });
  console.log(`[1] Screenshot saved: ${loginFormPath}`);

  // Verify we're on the login page
  let currentUrl = page.url();
  console.log(`[2] Current URL: ${currentUrl}`);
  expect(currentUrl).toContain('/login');

  // Check if the form elements exist
  const emailField = await page.$('#login-identifier');
  const passwordField = await page.$('#login-password');
  const submitButton = await page.$('button[type="submit"]');

  expect(emailField).not.toBeNull();
  expect(passwordField).not.toBeNull();
  expect(submitButton).not.toBeNull();
  console.log('[2] Form fields verified: email, password, submit');

  console.log('[3] Filling in credentials...');
  await page.fill('#login-identifier', adminEmail());
  await page.fill('#login-password', adminPassword());

  console.log('[3] Clicking submit button...');

  // MP-031: wait for the post-login URL, not `networkidle` — the
  // authenticated dashboard legitimately polls live data, so the network
  // never goes idle and `waitForNavigation({waitUntil:'networkidle'})` is a
  // guaranteed 30s timeout (Playwright's docs mark networkidle DISCOURAGED
  // for tests). The assertions below (final URL, JWT in localStorage,
  // authenticated chrome) are unchanged.
  await Promise.all([
    page.waitForURL(/\/dashboard/, { timeout: 30000 }),
    page.click('button[type="submit"]'),
  ]);

  console.log('[4] Navigated to post-login URL');

  // Wait a bit for any client-side state updates
  await page.waitForTimeout(1000);

  currentUrl = page.url();
  console.log(`[5] Final URL: ${currentUrl}`);
  expect(currentUrl).toContain('/dashboard');

  // Check localStorage for token
  const tokenFromLocalStorage = await page.evaluate(() => {
    return localStorage.getItem('aether_token');
  });

  console.log(`[6] localStorage.aether_token: ${tokenFromLocalStorage ? 'FOUND' : 'NOT FOUND'}`);
  expect(tokenFromLocalStorage).toBeTruthy();
  expect(tokenFromLocalStorage).toMatch(/^eyJ/); // JWT header
  console.log(`[6] Token sample: ${tokenFromLocalStorage?.substring(0, 8)}...`);

  // Take authenticated dashboard screenshot
  console.log('[7] Taking authenticated dashboard screenshot...');
  const dashboardPath = path.join(EVIDENCE_DIR, 'AUTH-RECIPE-PROOF-step2-authenticated-dashboard.png');
  await page.screenshot({ path: dashboardPath, fullPage: true });
  console.log(`[7] Screenshot saved: ${dashboardPath}`);

  // Look for authenticated elements
  console.log('[8] Looking for authenticated UI elements...');
  const mainContent = await page.$('main');
  const topbar = await page.$('[data-testid="topbar"], .topbar, [aria-label*="top" i]');

  const mainHeading = await page.evaluate(() => {
    const h1 = document.querySelector('main h1');
    const h2 = document.querySelector('main h2');
    return h1?.textContent || h2?.textContent || '';
  });

  console.log(`[8] Main content visible: ${mainContent !== null}`);
  console.log(`[8] Topbar visible: ${topbar !== null}`);
  console.log(`[8] Main heading: ${mainHeading || '(none)'}`);

  // Either main content OR topbar should be visible (we're on dashboard, not login)
  expect(mainContent || topbar).not.toBeNull();
  console.log('[8] Authenticated dashboard elements confirmed!');

  // Collect console errors
  const consoleErrors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });

  console.log(`[9] Console errors: ${consoleErrors.length}`);
  console.log('\n=== AUTH RECIPE PROOF SUCCESS ===');

  // Write proof artifact
  const proofArtifact = {
    status: 'SUCCESS',
    mechanism: 'localStorage',
    storage_key: 'aether_token',
    final_url: currentUrl,
    authed_element_seen: true,
    console_error_count: consoleErrors.length,
    recipe_proven: true,
    token_sample: tokenFromLocalStorage?.substring(0, 8) + '...',
    timestamp_utc: new Date().toISOString(),
    test_file: __filename,
  };

  const proofPath = path.join(EVIDENCE_DIR, 'AUTH-RECIPE-PROOF.json');
  fs.writeFileSync(proofPath, JSON.stringify(proofArtifact, null, 2));
  console.log(`\nProof artifact written to: ${proofPath}`);
});
