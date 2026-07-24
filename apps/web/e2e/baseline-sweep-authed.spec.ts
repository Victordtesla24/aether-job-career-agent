/**
 * BASELINE SWEEP: Authenticated Routes
 *
 * Captures baseline screenshots for all authenticated dashboard routes using
 * the proven login recipe from AUTH-RECIPE-PROOF.
 *
 * Scope: /dashboard/* and /admin/* routes
 * Auth: Logs in as admin/admin123 (free-plan, non-admin user)
 * Captures: Desktop + mobile viewports, console + request tracking
 */

import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EVIDENCE_DIR = '/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/manual-verification/screens';
const PROD_URL = 'https://5cb5f0620.abacusai.cloud';

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

console.log(`[TEST] Preparing to capture ${authenticatedRoutes.length} authenticated routes`);

test.describe('Baseline Sweep: Authenticated Routes', () => {
  // Create a shared authenticated context once per test suite
  test.beforeAll(async ({ browser }) => {
    // Context will be created in the setup phase
  });

  for (const screen of authenticatedRoutes) {
    const screenId = screen.screen_id;
    const route = screen.routes[0];
    const isMobile = screenId.startsWith('mobile-');

    test(`capture ${screenId}`, async ({ page }) => {
      // Set viewport based on screen type
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

      // Navigate (use full URL to bypass baseURL config)
      const navStart = Date.now();
      const response = await page.goto(url, {
        waitUntil: 'networkidle',
        timeout: 30000,
      });
      const loadTime = Date.now() - navStart;

      // Wait a bit for client-side hydration
      await page.waitForTimeout(500);

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
        authed: !finalUrl.includes('/login'), // Verify we stayed authenticated
        notes: screen.notes || '',
      };

      fs.writeFileSync(baselineFile, JSON.stringify(baseline, null, 2));

      // Verify authentication
      expect(finalUrl).not.toContain('/login', `Route ${route} redirected to login`);

      // Write summary line
      console.log(`[BASELINE] ${screenId} | ${finalUrl} | console_errors=${baseline.console_messages.length} | load_ms=${loadTime}`);
    });
  }
});
