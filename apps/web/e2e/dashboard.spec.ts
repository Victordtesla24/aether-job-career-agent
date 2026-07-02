import { test, expect } from "@playwright/test";

/**
 * Smoke test for the dashboard shell (P1-S06). Verifies the page renders and
 * that all 12 primary navigation items from the Schema-A contract are present
 * in the sidebar, in order. Detailed content is covered by unit tests and later
 * slices; this is an end-to-end sanity check of the shell.
 */
const EXPECTED_NAV = [
  "Dashboard",
  "Jobs",
  "Resume Studio",
  "Story Bank",
  "Applications",
  "Interview Center",
  "Networking",
  "Email Center",
  "Agents",
  "Analytics",
  "Offers",
  "Settings",
];

test("dashboard renders the 12-item primary sidebar", async ({ page }) => {
  await page.goto("/dashboard");

  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav).toBeVisible();

  const links = nav.getByRole("link");
  await expect(links).toHaveCount(EXPECTED_NAV.length);

  for (let i = 0; i < EXPECTED_NAV.length; i += 1) {
    await expect(links.nth(i)).toContainText(EXPECTED_NAV[i]);
  }
});

test("root route redirects to the dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("un-built nav sections render a graceful placeholder, not a 404 (P1-S12)", async ({
  page,
}) => {
  await page.goto("/dashboard/interviews");

  // The shell stays intact and the section is titled from the nav contract.
  const heading = page.getByRole("heading", { name: "Interview Center", level: 2 });
  await expect(heading).toBeVisible();
  await expect(page.getByText(/planned workspace/i)).toBeVisible();

  // The correct sidebar item is marked active for the current pathname.
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Interview Center" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
