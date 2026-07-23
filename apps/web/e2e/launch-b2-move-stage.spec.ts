import { test, expect, type Page } from "@playwright/test";

/**
 * FEAT-B2 e2e — move applications between kanban stages.
 *
 * State-restoring against live data: every move performed here is moved BACK
 * in the same test, so the board ends exactly where it started. Covers the
 * accessible "Move to…" menu path, the HTML5 drag-and-drop path, reload
 * persistence, and the server's honest 422 on an illegal cross-split move
 * (the menu never offers illegal targets, so the 422 is proven at the API —
 * the same request a hand-rolled drag payload would produce).
 */

const API = "http://127.0.0.1:8000";
const APP_STAGES = ["ready", "submitted", "in-review", "interview", "offer"] as const;

async function apiToken(page: Page): Promise<string> {
  await page.goto("/dashboard/applications");
  const token = await page.evaluate(() => localStorage.getItem("aether_token") ?? "");
  expect(token, "authenticated session token present").toBeTruthy();
  return token;
}

/** First application-fed column that has at least one card, or null. */
async function findAppCard(page: Page) {
  for (const stage of APP_STAGES) {
    const column = page.getByTestId(`kanban-column-${stage}`);
    const card = column.getByTestId("application-card").first();
    if ((await card.count()) > 0 && (await card.isVisible())) {
      return { stage, column, card };
    }
  }
  return null;
}

test.describe("FEAT-B2: stage moves", () => {
  test("every card exposes an accessible Move to… menu with only legal targets", async ({
    page,
  }) => {
    await page.goto("/dashboard/applications");
    await expect(page.getByTestId("applications-kanban")).toBeVisible({ timeout: 20_000 });

    const found = await findAppCard(page);
    test.skip(!found, "no application cards on the live board to inspect");
    const { card } = found!;

    const menuBtn = card.getByTestId("move-menu-btn");
    await expect(menuBtn).toBeVisible();
    await expect(menuBtn).toHaveAttribute("aria-haspopup", "menu");
    // Keyboard path: focus + Enter opens the menu.
    await menuBtn.focus();
    await page.keyboard.press("Enter");
    const menu = card.getByRole("menu");
    await expect(menu).toBeVisible();
    // Application cards may only offer the 5 app-fed stages — never the
    // agent-pipeline columns.
    for (const illegal of ["discovered", "evaluating", "tailoring"]) {
      await expect(menu.getByTestId(`move-option-${illegal}`)).toHaveCount(0);
    }
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
  });

  test("menu move persists across reload, then moves back (state restored)", async ({
    page,
  }) => {
    await page.goto("/dashboard/applications");
    await expect(page.getByTestId("applications-kanban")).toBeVisible({ timeout: 20_000 });

    const found = await findAppCard(page);
    test.skip(!found, "no application cards on the live board to move");
    const { stage: fromStage, card } = found!;
    const title = (await card.getByRole("heading").first().textContent())?.trim() ?? "";
    expect(title).not.toBe("");
    const toStage = APP_STAGES.find((s) => s !== fromStage)!;
    const fromColumn = page.getByTestId(`kanban-column-${fromStage}`);
    const toColumn = page.getByTestId(`kanban-column-${toStage}`);
    const countIn = (col: typeof toColumn) =>
      col.getByTestId("application-card").filter({ hasText: title });

    // Move via the accessible menu.
    await card.getByTestId("move-menu-btn").click();
    await card.getByTestId(`move-option-${toStage}`).click();
    await expect(countIn(toColumn).first()).toBeVisible({ timeout: 20_000 });
    await expect(countIn(fromColumn)).toHaveCount(0);

    // Reload — the move is server-persisted, not client-side sleight of hand.
    await page.reload();
    await expect(page.getByTestId("applications-kanban")).toBeVisible({ timeout: 20_000 });
    await expect(countIn(toColumn).first()).toBeVisible({ timeout: 20_000 });
    await expect(countIn(fromColumn)).toHaveCount(0);

    // Restore: move the card back to its original stage via the menu.
    const movedCard = countIn(toColumn).first();
    await movedCard.getByTestId("move-menu-btn").click();
    await movedCard.getByTestId(`move-option-${fromStage}`).click();
    await expect(countIn(fromColumn).first()).toBeVisible({ timeout: 20_000 });
    await expect(countIn(toColumn)).toHaveCount(0);
  });

  test("drag-and-drop moves a card between columns, then drags it back", async ({
    page,
  }) => {
    await page.goto("/dashboard/applications");
    await expect(page.getByTestId("applications-kanban")).toBeVisible({ timeout: 20_000 });

    const found = await findAppCard(page);
    test.skip(!found, "no application cards on the live board to drag");
    const { stage: fromStage, card } = found!;
    const title = (await card.getByRole("heading").first().textContent())?.trim() ?? "";
    const toStage = APP_STAGES.find((s) => s !== fromStage)!;
    const fromColumn = page.getByTestId(`kanban-column-${fromStage}`);
    const toColumn = page.getByTestId(`kanban-column-${toStage}`);
    const countIn = (col: typeof toColumn) =>
      col.getByTestId("application-card").filter({ hasText: title });

    await card.dragTo(toColumn);
    await expect(countIn(toColumn).first()).toBeVisible({ timeout: 20_000 });
    await expect(countIn(fromColumn)).toHaveCount(0);

    // Restore by dragging back.
    await countIn(toColumn).first().dragTo(fromColumn);
    await expect(countIn(fromColumn).first()).toBeVisible({ timeout: 20_000 });
    await expect(countIn(toColumn)).toHaveCount(0);
  });

  test("illegal cross-split move is rejected with an honest 422", async ({ page }) => {
    const token = await apiToken(page);
    const auth = { Authorization: `Bearer ${token}` };

    const res = await page.request.get(`${API}/applications`, { headers: auth });
    expect(res.ok()).toBeTruthy();
    const apps = (await res.json()) as Array<{ id: string; status: string }>;
    const movable = apps.find((a) => !["rejected", "withdrawn"].includes(a.status));
    test.skip(!movable, "no movable applications on the live server");

    // Application → job-fed stage: 422, and the application is untouched.
    const illegal = await page.request.post(
      `${API}/applications/${movable!.id}/move`,
      { headers: auth, data: { to_stage: "discovered" } },
    );
    expect(illegal.status()).toBe(422);
    const detail = ((await illegal.json()) as { detail: string }).detail;
    expect(detail).toContain("Job");

    const after = await page.request.get(`${API}/applications/${movable!.id}`, {
      headers: auth,
    });
    expect(((await after.json()) as { status: string }).status).toBe(movable!.status);

    // Unknown stage key: also an honest 422.
    const unknown = await page.request.post(
      `${API}/applications/${movable!.id}/move`,
      { headers: auth, data: { to_stage: "not-a-stage" } },
    );
    expect(unknown.status()).toBe(422);
  });
});
