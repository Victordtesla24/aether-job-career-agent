import { test, expect, type Page } from "@playwright/test";

/**
 * FEAT-B1 e2e — remove stale/expired approval requests.
 *
 * Non-destructive against live data: the spec creates its OWN approval via
 * the API, resolves it (reject), removes it through the real UI card button
 * (accepting the confirm dialog), and proves the removal survives a reload.
 * The bulk "Clear expired (N)" control is asserted conditionally — expiry is
 * decided server-side by real timestamps, so the button only exists when the
 * live queue actually contains expired rows (never fabricated here).
 */

const API = "http://127.0.0.1:8000";

async function apiToken(page: Page): Promise<string> {
  // storageState already logged us in; reuse the same session token.
  await page.goto("/dashboard/approvals");
  const token = await page.evaluate(() => localStorage.getItem("aether_token") ?? "");
  expect(token, "authenticated session token present").toBeTruthy();
  return token;
}

test.describe("FEAT-B1: remove approval requests", () => {
  test("resolved approval card exposes Remove; removal persists across reload", async ({
    page,
  }) => {
    const token = await apiToken(page);
    const auth = { Authorization: `Bearer ${token}` };

    // Arrange: create a dedicated approval and resolve it (reject) via API.
    const marker = `E2E-B1-${Date.now()}`;
    const created = await page.request.post(`${API}/approvals`, {
      headers: auth,
      data: {
        type: "application_submit",
        payload: { kind: "cover_letter", job_title: marker, company: "E2E Co" },
      },
    });
    expect(created.status()).toBe(201);
    const approval = (await created.json()) as { id: string };
    const rejected = await page.request.post(`${API}/approvals/${approval.id}/reject`, {
      headers: auth,
    });
    expect(rejected.ok()).toBeTruthy();

    // Act: find the card under the "rejected" filter and remove it via the UI.
    await page.goto("/dashboard/approvals");
    await page.getByRole("button", { name: "rejected", exact: true }).click();
    const card = page
      .getByTestId("approval-card")
      .filter({ hasText: marker })
      .first();
    await expect(card).toBeVisible({ timeout: 20_000 });
    const removeBtn = card.getByTestId("remove-btn");
    await expect(removeBtn).toBeVisible();

    page.once("dialog", (dialog) => void dialog.accept());
    await removeBtn.click();

    // Assert: gone from the list, and STILL gone after a full reload (no
    // zombie row hiding behind client state).
    await expect(
      page.getByTestId("approval-card").filter({ hasText: marker }),
    ).toHaveCount(0, { timeout: 20_000 });
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Approvals", level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByTestId("approval-card").filter({ hasText: marker }),
    ).toHaveCount(0, { timeout: 20_000 });

    // Server truth: the row is hard-deleted (second delete honest 404).
    const gone = await page.request.delete(`${API}/approvals/${approval.id}`, {
      headers: auth,
    });
    expect(gone.status()).toBe(404);
  });

  test("live pending approvals cannot be removed (409) and show no Remove button", async ({
    page,
  }) => {
    const token = await apiToken(page);
    const auth = { Authorization: `Bearer ${token}` };

    const marker = `E2E-B1-PENDING-${Date.now()}`;
    const created = await page.request.post(`${API}/approvals`, {
      headers: auth,
      data: {
        type: "application_submit",
        payload: { kind: "cover_letter", job_title: marker, company: "E2E Co" },
      },
    });
    expect(created.status()).toBe(201);
    const approval = (await created.json()) as { id: string };

    // UI: the fresh pending card has Approve/Reject but NO Remove.
    await page.goto("/dashboard/approvals");
    const card = page
      .getByTestId("approval-card")
      .filter({ hasText: marker })
      .first();
    await expect(card).toBeVisible({ timeout: 20_000 });
    await expect(card.getByTestId("approve-btn")).toBeVisible();
    await expect(card.getByTestId("remove-btn")).toHaveCount(0);

    // API: deleting a live pending approval is an honest 409, not a bypass.
    const del = await page.request.delete(`${API}/approvals/${approval.id}`, {
      headers: auth,
    });
    expect(del.status()).toBe(409);

    // Clean up: resolve then remove our own test row.
    await page.request.post(`${API}/approvals/${approval.id}/reject`, { headers: auth });
    const cleanup = await page.request.delete(`${API}/approvals/${approval.id}`, {
      headers: auth,
    });
    expect(cleanup.ok()).toBeTruthy();
  });

  test("bulk Clear expired control matches the server-side expired count", async ({
    page,
  }) => {
    const token = await apiToken(page);
    const auth = { Authorization: `Bearer ${token}` };

    // Server-side truth: count pending rows older than 48h.
    const res = await page.request.get(`${API}/approvals?status=all`, { headers: auth });
    expect(res.ok()).toBeTruthy();
    const rows = (await res.json()) as Array<{ status: string; createdAt: string }>;
    const cutoff = Date.now() - 48 * 3600 * 1000;
    const expired = rows.filter(
      (r) => r.status === "pending" && new Date(r.createdAt).getTime() < cutoff,
    ).length;

    await page.goto("/dashboard/approvals");
    await page.getByRole("button", { name: "all", exact: true }).click();
    await expect(
      page.getByTestId("approval-card").first().or(page.getByTestId("approvals-empty-state")),
    ).toBeVisible({ timeout: 20_000 });

    const clearBtn = page.getByTestId("clear-expired-btn");
    if (expired > 0) {
      // Honest count in the label; we do NOT click it here (bulk purge of
      // live user data belongs to the dedicated prod verification, not a
      // repeatable smoke test).
      await expect(clearBtn).toContainText(`(${expired})`);
    } else {
      await expect(clearBtn).toHaveCount(0);
    }
  });
});
