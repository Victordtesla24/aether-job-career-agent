import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PRODUCTION_URL = "https://5cb5f0620.abacusai.cloud";

test.describe("GOLD-MASTER-V3 Baseline Sweep", () => {
  const baseScreenshotsDir = path.join(__dirname, "../../../uat/reports/evidence/gold-master-v3/browser/baseline");
  const reportsDir = path.join(__dirname, "../../../uat/reports/evidence/gold-master-v3/browser");
  const results: any[] = [];

  test.beforeAll(() => {
    fs.mkdirSync(baseScreenshotsDir, { recursive: true });
    fs.mkdirSync(reportsDir, { recursive: true });
  });

  test.afterAll(async () => {
    // Generate final report
    const totalConsoleErrors = results.reduce((sum, r) => sum + r.consoleErrors.length, 0);
    const totalFailedRequests = results.reduce((sum, r) => sum + r.failedRequests.length + r.serverErrors.length, 0);

    const reportContent = `# BASELINE-SWEEP.md
Generated: ${new Date().toISOString()} (UTC)

## Summary
- Routes swept: ${results.length}
- Total console errors: ${totalConsoleErrors}
- Total failed requests: ${totalFailedRequests}
- Production URL: ${PRODUCTION_URL}

## Route Summary Table

| Route | HTTP Status | Console Errors | Failed Requests | Data State | Screenshot | Notes |
|-------|-------------|---|---|---|---|---|
${results
  .map(
    (r) =>
      `| \`${r.route}\` | ${r.httpStatus} | ${r.consoleErrors.length} | ${r.failedRequests.length + r.serverErrors.length} | ${r.dataState} | [${path.basename(r.screenshotPath)}](${path.basename(r.screenshotPath)}) | ${r.notes || r.placeholderFlags.join(", ") || "OK"} |`
  )
  .join("\n")}

## Baseline Findings

${
  results
    .filter((r) => r.consoleErrors.length > 0 || r.failedRequests.length > 0 || r.serverErrors.length > 0 || r.placeholderFlags.length > 0)
    .map(
      (r) =>
        `### Route: \`${r.route}\`
- Final URL: ${r.finalUrl}
- HTTP Status: ${r.httpStatus}
- Console Errors: ${r.consoleErrors.length}
${r.consoleErrors.map((e: any) => `  - ${e.type}: ${e.message}`).join("\n")}
- Failed Requests: ${r.failedRequests.length + r.serverErrors.length}
${r.failedRequests.map((e: any) => `  - ${e.method} ${e.url} (${e.status})`).join("\n")}
${r.serverErrors.map((e: any) => `  - GET ${e.url} (${e.status})`).join("\n")}
- Placeholder Flags: ${r.placeholderFlags.join(", ") || "none"}
- Data State: ${r.dataState}
`
    )
    .join("\n")
}
`;

    const reportPath = path.join(reportsDir, "BASELINE-SWEEP.md");
    fs.writeFileSync(reportPath, reportContent);
    console.log(`✅ Report written to: ${reportPath}`);
    console.log(`📸 Screenshots: ${baseScreenshotsDir}`);
  });

  const routes = [
    "/login",
    "/",
    "/dashboard",
    "/dashboard/agents",
    "/dashboard/analytics",
    "/dashboard/applications",
    "/dashboard/approvals",
    "/dashboard/cover-letters",
    "/dashboard/email",
    "/dashboard/interviews",
    "/dashboard/jobs",
    "/dashboard/networking",
    "/dashboard/offers",
    "/dashboard/resume",
    "/dashboard/settings",
    "/dashboard/stories",
    "/admin-login",
    "/admin",
    "/admin/audit-log",
    "/admin/health",
    "/admin/settings",
    "/admin/spend",
    "/admin/users",
    "/pricing",
    "/privacy-policy",
    "/signup",
    "/terms",
    "/forgot-password",
  ];

  for (const route of routes) {
    test(`Sweep route: ${route}`, async ({ page }) => {
      const consoleErrors: any[] = [];
      const failedRequests: any[] = [];
      const serverErrors: any[] = [];
      let httpStatus = 0;
      let placeholderFlags: string[] = [];

      // Attach listeners BEFORE navigation
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          consoleErrors.push({
            type: msg.type(),
            message: msg.text(),
            location: msg.location().url,
          });
        }
      });

      page.on("pageerror", (error) => {
        consoleErrors.push({
          type: "pageerror",
          message: error.message || String(error),
        });
      });

      page.on("requestfailed", (request) => {
        const failure = request.failure();
        failedRequests.push({
          url: request.url(),
          status: failure?.errorText || "unknown",
          method: request.method(),
        });
      });

      page.on("response", (response) => {
        if (response.status() >= 400) {
          serverErrors.push({
            url: response.url(),
            status: response.status(),
          });
        }
      });

      // Navigate to route
      const response = await page.goto(`${PRODUCTION_URL}${route}`, {
        waitUntil: "networkidle",
        timeout: 30000,
      });
      httpStatus = response?.status() || 0;

      // Light exercise: scroll if not login page
      if (!route.includes("login") && !route.includes("forgot-password")) {
        try {
          await page.evaluate(() => window.scrollBy(0, 300));
        } catch (e) {
          // Ignore scroll errors
        }
      }

      // Wait for lazy-loaded content
      await page.waitForTimeout(500);

      // Check for placeholder text
      const bodyText = await page.evaluate(() => document.body.innerText);
      const placeholders = [
        "Coming Soon",
        "In Planning",
        "Not Implemented",
        "Lorem ipsum",
        "placeholder",
        "fixture",
      ];
      placeholderFlags = placeholders.filter((p) =>
        bodyText.toLowerCase().includes(p.toLowerCase())
      );

      // Determine data state
      let dataState = "live";
      if (placeholderFlags.length > 0) dataState = "placeholder";
      else if (bodyText.match(/loading|please wait/i)) dataState = "loading";
      else if (bodyText.trim().length < 100) dataState = "empty";

      // Take screenshot
      const screenshotName = route.replace(/\//g, "-").replace(/^-/, "") || "root";
      const screenshotPath = path.join(baseScreenshotsDir, `${screenshotName}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });

      results.push({
        route,
        finalUrl: page.url(),
        httpStatus,
        consoleErrors,
        failedRequests: failedRequests.filter((r) => typeof r.status === "string"),
        serverErrors,
        dataState,
        placeholderFlags,
        screenshotPath,
        notes: "",
      });

      // Don't fail the test - we're just collecting data
      expect(true).toBe(true);
    });
  }
});
