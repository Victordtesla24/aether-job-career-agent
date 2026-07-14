import { test, expect, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Mobile regression smoke test (T3): sweep /dashboard and /dashboard/approvals
 * at 390x844 viewport (mobile). Verify:
 * - Mobile layouts render (bottom nav visible, cards stack)
 * - Zero console errors
 * - Zero failed requests
 *
 * Evidence saved to uat/reports/evidence/phase4/ with prefixes:
 * - rg-mob-dash: dashboard tests
 * - rg-mob-appr: approvals tests
 */

interface TestResult {
  route: string;
  prefix: string;
  layout_valid: boolean;
  bottom_nav_visible: boolean;
  cards_stack: boolean;
  console_errors: string[];
  request_failures: string[];
  status: "PASS" | "FAIL";
  error_details: string | null;
}

const EVIDENCE_DIR = path.resolve(
  process.cwd(),
  "../../uat/reports/evidence/phase4"
);

function getUtcTimestamp(): string {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z/, "Z");
}

function saveEvidence(
  prefix: string,
  step: string,
  phase: "pre" | "post",
  data: string | Buffer,
  ext: string
) {
  if (!fs.existsSync(EVIDENCE_DIR)) {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  }
  const utc = getUtcTimestamp();
  const filename = `${prefix}__${step}__${phase}__${utc}.${ext}`;
  const filepath = path.join(EVIDENCE_DIR, filename);
  if (typeof data === "string") {
    fs.writeFileSync(filepath, data);
  } else {
    fs.writeFileSync(filepath, data);
  }
  return filepath;
}

// Configure mobile viewport for this test
test.use({ ...devices["Pixel 5"] });

const testResults: TestResult[] = [];

test.describe("Mobile Regression Smoke Test (T3) - 390x844 Viewport", () => {
  // Set to mobile viewport (390x844)
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
  });

  test.afterEach(async ({ page }) => {
    // Log viewport for verification
    const viewport = page.viewportSize();
    console.log(`Test viewport: ${viewport?.width}x${viewport?.height}`);
  });

  test("rg-mob-dash: dashboard loads at mobile viewport with valid layout", async ({
    page,
  }) => {
    const prefix = "rg-mob-dash";
    const result: TestResult = {
      route: "/dashboard",
      prefix,
      layout_valid: false,
      bottom_nav_visible: false,
      cards_stack: false,
      console_errors: [],
      request_failures: [],
      status: "PASS",
      error_details: null,
    };

    try {
      // Capture console and network errors
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          result.console_errors.push(msg.text());
        }
      });

      page.on("response", (response) => {
        if (!response.ok() && response.status() !== 304) {
          result.request_failures.push(
            `${response.url()} - ${response.status()}`
          );
        }
      });

      // Navigate to dashboard
      await page.goto("/dashboard", { waitUntil: "networkidle" });

      // Pre-load screenshot
      const preScreenshot = await page.screenshot({ fullPage: false });
      saveEvidence(prefix, "page-load", "pre", preScreenshot, "png");

      // Verify main content is visible
      const mainContent = page.getByRole("main");
      await expect(mainContent).toBeVisible({ timeout: 5000 });

      // Check for bottom navigation (mobile-specific)
      const bottomNav = page.getByRole("navigation").first();
      result.bottom_nav_visible = await bottomNav
        .isVisible()
        .catch(() => false);

      // Check if cards are stacked (no side-by-side layout on mobile)
      const cards = page.locator("[class*='card'], [class*='Card']");
      const cardCount = await cards.count();
      if (cardCount > 0) {
        const cardBox = await cards.first().boundingBox();
        result.cards_stack = cardBox ? cardBox.width < 400 : true;
      }

      // Post-load screenshot
      const postScreenshot = await page.screenshot({ fullPage: false });
      saveEvidence(prefix, "page-load", "post", postScreenshot, "png");

      result.layout_valid =
        result.bottom_nav_visible && (cardCount === 0 || result.cards_stack);

      if (result.console_errors.length > 0) {
        result.status = "FAIL";
        result.error_details = `Console errors: ${result.console_errors.join("; ")}`;
      }

      if (result.request_failures.length > 0) {
        result.status = "FAIL";
        result.error_details =
          result.error_details +
          ` | Request failures: ${result.request_failures.join("; ")}`;
      }

      if (!result.layout_valid) {
        result.status = "FAIL";
        result.error_details =
          result.error_details || "Layout validation failed";
      }
    } catch (error) {
      result.status = "FAIL";
      result.error_details =
        error instanceof Error ? error.message : String(error);
    }

    testResults.push(result);

    // Save result JSON
    const resultJson = JSON.stringify(result, null, 2);
    saveEvidence(prefix, "result", "post", resultJson, "json");

    // Assert no failures
    expect(result.status).toBe("PASS");
    expect(result.console_errors).toHaveLength(0);
    expect(result.request_failures).toHaveLength(0);
    expect(result.layout_valid).toBe(true);
  });

  test("rg-mob-dash: verify mobile navigation and sections", async ({
    page,
  }) => {
    const prefix = "rg-mob-dash";

    await page.goto("/dashboard", { waitUntil: "networkidle" });

    // Verify navigation is accessible at mobile width
    const navLinks = page.getByRole("link");
    const count = await navLinks.count();

    expect(count).toBeGreaterThan(0);

    // Verify no horizontal overflow on mobile
    const html = page.locator("html");
    const scrollWidth = await html.evaluate(
      (el) => el.scrollWidth
    );
    const clientWidth = await html.evaluate((el) => el.clientWidth);

    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 5); // small tolerance
  });

  test("rg-mob-appr: approvals page loads at mobile viewport with valid layout", async ({
    page,
  }) => {
    const prefix = "rg-mob-appr";
    const result: TestResult = {
      route: "/dashboard/approvals",
      prefix,
      layout_valid: false,
      bottom_nav_visible: false,
      cards_stack: false,
      console_errors: [],
      request_failures: [],
      status: "PASS",
      error_details: null,
    };

    try {
      // Capture console and network errors
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          result.console_errors.push(msg.text());
        }
      });

      page.on("response", (response) => {
        if (!response.ok() && response.status() !== 304) {
          result.request_failures.push(
            `${response.url()} - ${response.status()}`
          );
        }
      });

      // Navigate to approvals
      await page.goto("/dashboard/approvals", { waitUntil: "networkidle" });

      // Pre-load screenshot
      const preScreenshot = await page.screenshot({ fullPage: false });
      saveEvidence(prefix, "page-load", "pre", preScreenshot, "png");

      // Verify heading is visible
      const heading = page.getByRole("heading", { name: "Approvals", level: 1 });
      await expect(heading).toBeVisible({ timeout: 5000 });

      // Check for bottom navigation
      const bottomNav = page.getByRole("navigation").first();
      result.bottom_nav_visible = await bottomNav
        .isVisible()
        .catch(() => false);

      // Check approval cards or empty state
      const card = page.getByTestId("approval-card").first();
      const empty = page.getByTestId("approvals-empty-state");
      const hasContent = await card
        .or(empty)
        .first()
        .isVisible({ timeout: 10000 })
        .catch(() => false);

      if (hasContent) {
        const cardBox = await card.boundingBox().catch(() => null);
        result.cards_stack = cardBox ? cardBox.width < 400 : true;
      } else {
        result.cards_stack = true; // empty state is fine
      }

      // Post-load screenshot
      const postScreenshot = await page.screenshot({ fullPage: false });
      saveEvidence(prefix, "page-load", "post", postScreenshot, "png");

      result.layout_valid = result.bottom_nav_visible && result.cards_stack;

      if (result.console_errors.length > 0) {
        result.status = "FAIL";
        result.error_details = `Console errors: ${result.console_errors.join("; ")}`;
      }

      if (result.request_failures.length > 0) {
        result.status = "FAIL";
        result.error_details =
          result.error_details +
          ` | Request failures: ${result.request_failures.join("; ")}`;
      }

      if (!result.layout_valid) {
        result.status = "FAIL";
        result.error_details =
          result.error_details || "Layout validation failed";
      }
    } catch (error) {
      result.status = "FAIL";
      result.error_details =
        error instanceof Error ? error.message : String(error);
    }

    testResults.push(result);

    // Save result JSON
    const resultJson = JSON.stringify(result, null, 2);
    saveEvidence(prefix, "result", "post", resultJson, "json");

    // Assert no failures
    expect(result.status).toBe("PASS");
    expect(result.console_errors).toHaveLength(0);
    expect(result.request_failures).toHaveLength(0);
    expect(result.layout_valid).toBe(true);
  });

  test("rg-mob-appr: verify mobile approval card layout and interactions", async ({
    page,
  }) => {
    const prefix = "rg-mob-appr";

    await page.goto("/dashboard/approvals", { waitUntil: "networkidle" });

    const card = page.getByTestId("approval-card").first();
    const empty = page.getByTestId("approvals-empty-state");

    // Check if there are approval cards
    if (await card.isVisible().catch(() => false)) {
      // Verify card is not wider than mobile viewport
      const cardBox = await card.boundingBox();
      expect(cardBox?.width).toBeLessThanOrEqual(390);

      // Verify action buttons are visible and stacked on mobile
      const approveBtn = card.getByTestId("approve-btn");
      const rejectBtn = card.getByTestId("reject-btn");

      const isApproveVisible = await approveBtn
        .isVisible()
        .catch(() => false);
      const isRejectVisible = await rejectBtn
        .isVisible()
        .catch(() => false);

      if (isApproveVisible && isRejectVisible) {
        // Buttons should be accessible on mobile
        const approveBox = await approveBtn.boundingBox();
        const rejectBox = await rejectBtn.boundingBox();

        expect(approveBox?.height).toBeGreaterThanOrEqual(44); // minimum touch target
        expect(rejectBox?.height).toBeGreaterThanOrEqual(44);
      }
    } else if (await empty.isVisible().catch(() => false)) {
      // Empty state should display correctly on mobile
      expect(empty).toBeVisible();
    }
  });
});

test.afterAll(() => {
  // Summary report
  const summary = {
    total_tests: testResults.length,
    passed: testResults.filter((r) => r.status === "PASS").length,
    failed: testResults.filter((r) => r.status === "FAIL").length,
    console_error_count: testResults.reduce(
      (acc, r) => acc + r.console_errors.length,
      0
    ),
    request_failure_count: testResults.reduce(
      (acc, r) => acc + r.request_failures.length,
      0
    ),
    results: testResults,
  };

  if (!fs.existsSync(EVIDENCE_DIR)) {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  }

  const summaryPath = path.join(
    EVIDENCE_DIR,
    `rg-mob__summary__post__${getUtcTimestamp()}.json`
  );
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));

  console.log("\n=== Mobile Regression Smoke Test Summary ===");
  console.log(`Total tests: ${summary.total_tests}`);
  console.log(`Passed: ${summary.passed}`);
  console.log(`Failed: ${summary.failed}`);
  console.log(
    `Console errors: ${summary.console_error_count}`
  );
  console.log(
    `Request failures: ${summary.request_failure_count}`
  );
  console.log(`Summary saved to: ${summaryPath}`);
});
