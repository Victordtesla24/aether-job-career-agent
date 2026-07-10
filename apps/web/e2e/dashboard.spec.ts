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

test("nav sections render real workspaces; unknown routes get a graceful panel (P1-S12)", async ({
  page,
}) => {
  // Every nav section now has a dedicated workspace page.
  await page.goto("/dashboard/interviews");
  await expect(page.getByRole("heading", { name: "Interview Center", level: 1 })).toBeVisible();
  await expect(page.getByText(/planned workspace/i)).toHaveCount(0);

  // The correct sidebar item is marked active for the current pathname.
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Interview Center" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  // Unknown routes still render an in-shell graceful panel, not a bare 404.
  await page.goto("/dashboard/does-not-exist");
  await expect(page.getByRole("heading", { name: "Section not found", level: 2 })).toBeVisible();
  await expect(page.getByText(/unknown route/i)).toBeVisible();
});
