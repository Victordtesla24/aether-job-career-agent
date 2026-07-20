import { test, expect, request as apiRequest, Browser } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * MANUAL-VERIFICATION Phase 0, Step 6: Baseline Capture
 *
 * Captures baseline screenshots and metadata for all 29 routes in SCREEN-MATRIX.json.
 * Handles auth contexts (public, authenticated, admin dual-mode) and mobile viewports.
 *
 * Usage: npx playwright test --config=playwright.config.ts apps/web/e2e/baseline-manual-verification.spec.ts
 */

test.use({ storageState: { cookies: [], origins: [] } });

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BASE_URL = (process.env.BASE_URL || "https://5cb5f0620.abacusai.cloud").replace(/\/+$/, "");
const API_BASE = `${BASE_URL}/api`;
const TOKEN_STORAGE_KEY = "aether_token";

const E2E_EMAIL = "admin";
const E2E_PASSWORD = "admin123";

const REPO_ROOT = path.resolve(__dirname, "../../..");
const EVIDENCE_ROOT = path.join(REPO_ROOT, "uat/reports/evidence/manual-verification");
const SCREEN_MATRIX_PATH = path.join(EVIDENCE_ROOT, "screens/SCREEN-MATRIX.json");
const BASELINE_DIR = path.join(EVIDENCE_ROOT, "screens/baseline");

const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
const MOBILE_VIEWPORT = { width: 390, height: 844 };

// Load screen matrix
function loadScreenMatrix() {
  const raw = fs.readFileSync(SCREEN_MATRIX_PATH, "utf8");
  return JSON.parse(raw);
}

// Organize by auth requirement
function organizeScreensByAuth(matrix) {
  const byAuth = {
    public: [],
    authenticated: [],
    adminDualMode: [],
  };

  const publicRoutes = ["/", "/login", "/signup", "/pricing", "/privacy-policy", "/terms"];
  const adminRoutes = ["/admin", "/admin/health", "/admin/users", "/admin/settings", "/admin/audit-log", "/admin/spend"];

  for (const screen of matrix) {
    const firstRoute = screen.routes[0];

    if (adminRoutes.some(r => firstRoute === r || firstRoute.startsWith(r + "/"))) {
      byAuth.adminDualMode.push(screen);
    } else if (publicRoutes.includes(firstRoute)) {
      byAuth.public.push(screen);
    } else if (firstRoute.startsWith("/dashboard")) {
      byAuth.authenticated.push(screen);
    }
  }

  return byAuth;
}

// Login helper via UI
async function loginAndGetToken(browser) {
  const context = await browser.newContext({ viewport: DESKTOP_VIEWPORT });
  const page = await context.newPage();

  try {
    await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle", timeout: 30000 });
    await page.fill("#login-identifier", E2E_EMAIL);
    await page.fill("#login-password", E2E_PASSWORD);
    await page.click("button[type='submit']");
    await page.waitForURL("**/dashboard**", { timeout: 30000 });

    const token = await page.evaluate((key) => localStorage.getItem(key), TOKEN_STORAGE_KEY);
    if (!token) {
      throw new Error("No token in localStorage after login");
    }

    await page.close();
    await context.close();
    return token;
  } catch (err) {
    await context.close();
    throw new Error(`Login failed: ${err.message}`);
  }
}

// Capture screen function
async function captureScreen(page, screen, authMode, results) {
  const screenId = screen.screen_id;
  const route = screen.routes[0];
  const isMobile = screenId.startsWith("mobile-");
  const viewport = isMobile ? MOBILE_VIEWPORT : DESKTOP_VIEWPORT;

  const url = `${BASE_URL}${route}`;
  const consoleMessages = [];
  const failedRequests = [];
  let finalUrl = url;
  let docStatus = 0;
  let pageTitle = "";
  let mainHeading = "";
  let loadTime = 0;

  // Set viewport
  await page.setViewportSize(viewport);

  // Intercept console
  const consoleHandler = (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      consoleMessages.push({
        type: msg.type(),
        text: msg.text(),
      });
    }
  };
  page.on("console", consoleHandler);

  // Intercept failed requests
  const requestFailHandler = (req) => {
    if (req.failure()) {
      failedRequests.push({
        url: req.url(),
        method: req.method(),
        error: req.failure().errorText,
      });
    }
  };
  page.on("requestfailed", requestFailHandler);

  try {
    const navStart = Date.now();
    const response = await page.goto(url, {
      waitUntil: "networkidle",
      timeout: 30000,
    });
    loadTime = Date.now() - navStart;

    finalUrl = page.url();
    docStatus = response?.status() || 0;
    pageTitle = await page.title();
    mainHeading = await page.evaluate(() => {
      const h1 = document.querySelector("h1");
      const main = document.querySelector("main");
      return h1?.textContent || main?.getAttribute("aria-label") || "";
    });

    // Screenshot
    const screenshotDir = path.join(BASELINE_DIR, screenId);
    fs.mkdirSync(screenshotDir, { recursive: true });

    let screenshotPath = "";
    if (authMode === "admin-dual-unauth") {
      screenshotPath = path.join(screenshotDir, `${screenId}-unauth.png`);
    } else if (authMode === "admin-dual-authed") {
      screenshotPath = path.join(screenshotDir, `${screenId}-authed.png`);
    } else {
      screenshotPath = path.join(screenshotDir, `${screenId}.png`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });

    // Baseline JSON
    const baselineFile = path.join(screenshotDir, "baseline.json");
    const baseline = {
      timestamp_utc: new Date().toISOString(),
      url,
      final_url_after_redirects: finalUrl,
      document_http_status: docStatus,
      console_messages: consoleMessages,
      failed_requests: failedRequests,
      page_title: pageTitle,
      visible_h1_or_main_heading: mainHeading,
      load_time_ms: loadTime,
      viewport,
      auth_mode: authMode,
      notes: screen.notes || "",
    };

    fs.writeFileSync(baselineFile, JSON.stringify(baseline, null, 2));

    // Track results
    const errorCount = consoleMessages.filter(m => m.type === "error").length;
    const failedCount = failedRequests.length;
    results.captured.push({
      screen_id: screenId,
      status: "SUCCESS",
      console_error_count: errorCount,
      failed_request_count: failedCount,
      screenshot: screenshotPath.replace(REPO_ROOT, "."),
    });
    results.totalConsoleErrors += errorCount;
    results.totalFailedRequests += failedCount;

    expect.soft(true).toBe(true);

  } catch (err) {
    results.failed.push({
      screen_id: screenId,
      error: err.message,
    });
    expect.soft(false).toBe(true); // Soft fail so we continue
  } finally {
    page.off("console", consoleHandler);
    page.off("requestfailed", requestFailHandler);
  }
}

test("baseline capture sweep", async ({ browser }) => {
  // 45 routes * 60s per route = 45 min timeout
  test.setTimeout(60 * 60 * 1000);

  const matrix = loadScreenMatrix();
  const byAuth = organizeScreensByAuth(matrix);

  const results = {
    windowStart: new Date().toISOString(),
    captured: [],
    failed: [],
    totalConsoleErrors: 0,
    totalFailedRequests: 0,
  };

  // === PUBLIC ROUTES ===
  console.log("\n=== PUBLIC ROUTES ===");
  const publicContext = await browser.newContext({ viewport: DESKTOP_VIEWPORT });
  const publicPage = await publicContext.newPage();

  for (const screen of byAuth.public) {
    console.log(`Capturing ${screen.screen_id}...`);
    await captureScreen(publicPage, screen, "public", results);
  }

  await publicContext.close();

  // === AUTHENTICATED ROUTES ===
  console.log("\n=== AUTHENTICATED ROUTES ===");
  const token = await loginAndGetToken(browser);
  const authContext = await browser.newContext({
    viewport: DESKTOP_VIEWPORT,
  });

  // Inject token into storage
  await authContext.addInitScript((tokenKey, tokenValue) => {
    localStorage.setItem(tokenKey, tokenValue);
  }, TOKEN_STORAGE_KEY, token);

  const authPage = await authContext.newPage();

  for (const screen of byAuth.authenticated) {
    console.log(`Capturing ${screen.screen_id}...`);
    await captureScreen(authPage, screen, "authenticated", results);
  }

  await authContext.close();

  // === ADMIN DUAL-MODE (UNAUTHENTICATED) ===
  console.log("\n=== ADMIN DUAL-MODE (UNAUTHENTICATED) ===");
  const adminUnauthContext = await browser.newContext({ viewport: DESKTOP_VIEWPORT });
  const adminUnauthPage = await adminUnauthContext.newPage();

  for (const screen of byAuth.adminDualMode) {
    console.log(`Capturing ${screen.screen_id} (unauthenticated)...`);
    await captureScreen(adminUnauthPage, screen, "admin-dual-unauth", results);
  }

  await adminUnauthContext.close();

  // === ADMIN DUAL-MODE (AUTHENTICATED) ===
  console.log("\n=== ADMIN DUAL-MODE (AUTHENTICATED) ===");
  const adminAuthContext = await browser.newContext({
    viewport: DESKTOP_VIEWPORT,
  });

  await adminAuthContext.addInitScript((tokenKey, tokenValue) => {
    localStorage.setItem(tokenKey, tokenValue);
  }, TOKEN_STORAGE_KEY, token);

  const adminAuthPage = await adminAuthContext.newPage();

  for (const screen of byAuth.adminDualMode) {
    console.log(`Capturing ${screen.screen_id} (authenticated)...`);
    await captureScreen(adminAuthPage, screen, "admin-dual-authed", results);
  }

  await adminAuthContext.close();

  // === FINALIZE ===
  results.windowEnd = new Date().toISOString();

  fs.mkdirSync(BASELINE_DIR, { recursive: true });

  // Write window info
  const windowFile = path.join(EVIDENCE_ROOT, "screens/BASELINE-WINDOW.json");
  fs.writeFileSync(windowFile, JSON.stringify({
    window_start_utc: results.windowStart,
    window_end_utc: results.windowEnd,
    routes_swept: results.captured.length + results.failed.length,
    git_sha: "53f0e084da5b460835c32d3e07d496e6e67a8616",
  }, null, 2));

  // Write summary
  const summaryFile = path.join(EVIDENCE_ROOT, "screens/BASELINE-SUMMARY.json");
  fs.writeFileSync(summaryFile, JSON.stringify(results, null, 2));

  console.log("\n========== BASELINE CAPTURE COMPLETE ==========");
  console.log(`Captured: ${results.captured.length}`);
  console.log(`Failed: ${results.failed.length}`);
  console.log(`Total Console Errors: ${results.totalConsoleErrors}`);
  console.log(`Total Failed Requests: ${results.totalFailedRequests}`);

  expect(results.failed.length).toBe(0);
});
