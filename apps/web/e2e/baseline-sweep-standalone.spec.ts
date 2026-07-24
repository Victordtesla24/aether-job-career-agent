/**
 * BASELINE SWEEP: Standalone Authenticated Routes
 *
 * Captures baseline screenshots for authenticated dashboard routes against
 * PRODUCTION (https://5cb5f0620.abacusai.cloud) using admin/admin123 credentials.
 *
 * IMPORTANT: This test does NOT use the global auth setup. It logs in fresh
 * before each test session using the proven auth recipe.
 *
 * Run with:
 *   pnpm exec playwright test e2e/baseline-sweep-standalone.spec.ts --reporter=list
 */

import { test, expect, chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EVIDENCE_DIR = '/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/manual-verification/screens';
const PROD_URL = 'https://5cb5f0620.abacusai.cloud';
const ADMIN_EMAIL = 'admin';
const ADMIN_PASSWORD = 'admin123';

// Load SCREEN-MATRIX.json
const SCREEN_MATRIX_PATH = path.join(EVIDENCE_DIR, 'SCREEN-MATRIX.json');
// SCREEN-MATRIX.json was evicted to S3 in the launch-ready cleanup (W-D,
// DELETION-MANIFEST-1). Skip this evidence-capture sweep honestly when the
// matrix is absent instead of crashing the whole Playwright run at collection.
const screenMatrix: any[] = fs.existsSync(SCREEN_MATRIX_PATH)
  ? JSON.parse(fs.readFileSync(SCREEN_MATRIX_PATH, 'utf8'))
  : [];

// Filter authenticated routes
const authenticatedRoutes = screenMatrix.filter((screen: any) => {
  const route = screen.routes[0];
  return route.startsWith('/dashboard');
});

console.log(`[BASELINE-SWEEP] Preparing to capture ${authenticatedRoutes.length} authenticated routes`);

/**
 * Authenticate once and reuse the context for all tests
 */
let authContext: any = null;

test.beforeAll(async () => {
  console.log('[SETUP] Logging in to production with admin/admin123...');
  const browser = await chromium.launch({ headless: true });
  authContext = await browser.newContext();
  const loginPage = await authContext.newPage();

  try {
    // Navigate to login
    await loginPage.goto(`${PROD_URL}/login`, {
      waitUntil: 'domcontentloaded',
      timeout: 30000
    });

    // Fill and submit
    await loginPage.fill('#login-identifier', ADMIN_EMAIL);
    await loginPage.fill('#login-password', ADMIN_PASSWORD);

    const [response] = await Promise.all([
      loginPage.waitForNavigation({ waitUntil: 'networkidle', timeout: 30000 }),
      loginPage.click('button[type="submit"]'),
    ]);

    // Verify
    await loginPage.waitForTimeout(1000);
    const token = await loginPage.evaluate(() => localStorage.getItem('aether_token'));
    const finalUrl = loginPage.url();

    if (!token) throw new Error('No token in localStorage');
    if (!finalUrl.includes('/dashboard')) throw new Error(`Not on dashboard: ${finalUrl}`);

    console.log(`[SETUP] ✓ Logged in successfully to ${finalUrl}`);
    console.log(`[SETUP] ✓ Token: ${token.substring(0, 8)}...`);
  } catch (err) {
    console.error('[SETUP] FAILED:', (err as Error).message);
    throw err;
  } finally {
    await loginPage.close();
  }
});

test.afterAll(async () => {
  if (authContext) {
    await authContext.close();
  }
});

test.describe('Baseline Sweep: Authenticated Routes (Production)', () => {
  for (const screen of authenticatedRoutes) {
    const screenId = screen.screen_id;
    const route = screen.routes[0];
    const isMobile = screenId.startsWith('mobile-');

    test(`capture ${screenId}`, async () => {
      const page = await authContext.newPage();

      try {
        // Set viewport
        const viewport = isMobile
          ? { width: 390, height: 844 }
          : { width: 1440, height: 900 };
        await page.setViewportSize(viewport);

        const url = `${PROD_URL}${route}`;
        const consoleMessages: any[] = [];
        const failedRequests: any[] = [];

        // Intercept console
        page.on('console', (msg) => {
          consoleMessages.push({
            type: msg.type(),
            text: msg.text(),
          });
        });

        // Intercept failed requests
        page.on('requestfailed', (req) => {
          if (req.failure()) {
            failedRequests.push({
              url: req.url(),
              method: req.method(),
              error: req.failure().errorText,
            });
          }
        });

        // Navigate
        console.log(`[${screenId}] Navigating to ${route}`);
        const navStart = Date.now();
        const response = await page.goto(url, {
          waitUntil: 'networkidle',
          timeout: 30000,
        });
        const loadTime = Date.now() - navStart;

        await page.waitForTimeout(500); // Client-side hydration

        const finalUrl = page.url();
        const docStatus = response?.status() || 0;
        const pageTitle = await page.title();

        const mainHeading = await page.evaluate(() => {
          const h1 = document.querySelector('main h1');
          const h2 = document.querySelector('main h2');
          return h1?.textContent || h2?.textContent || '';
        });

        // Take screenshot
        const screenshotDir = path.join(EVIDENCE_DIR, 'baseline', screenId);
        fs.mkdirSync(screenshotDir, { recursive: true });
        const screenshotPath = path.join(screenshotDir, `${screenId}.png`);
        await page.screenshot({ path: screenshotPath, fullPage: true });

        // Write baseline.json
        const baselineFile = path.join(screenshotDir, 'baseline.json');
        const baseline = {
          timestamp_utc: new Date().toISOString(),
          url,
          final_url_after_redirects: finalUrl,
          document_http_status: docStatus,
          console_messages: consoleMessages.filter(m => ['error', 'warning'].includes(m.type)),
          failed_requests: failedRequests,
          page_title: pageTitle,
          visible_heading: mainHeading,
          load_time_ms: loadTime,
          viewport,
          auth_mode: 'authenticated',
          authed: !finalUrl.includes('/login'),
          notes: screen.notes || '',
        };

        fs.writeFileSync(baselineFile, JSON.stringify(baseline, null, 2));

        // Verify auth
        if (finalUrl.includes('/login')) {
          throw new Error(`Redirected to login - session lost for ${route}`);
        }

        const errorCount = baseline.console_messages.length;
        const failedCount = baseline.failed_requests.length;

        console.log(`[${screenId}] ✓ ${finalUrl} | errors=${errorCount} | failed=${failedCount} | load=${loadTime}ms`);
      } catch (err) {
        console.error(`[${screenId}] FAILED:`, (err as Error).message);
        throw err;
      } finally {
        await page.close();
      }
    });
  }
});
