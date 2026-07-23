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

/**
 * First application-fed column that has at least one card, or null.
 *
 * ``stages`` defaults to all 5 app-fed columns. The MOVE tests pass the list
 * WITHOUT "ready": the list endpoint collapses draft rows per job
 * (DISTINCT ON jobId — cover-letter version history shows one draft card per
 * job), so moving a draft out of "ready" can reveal an older shadowed draft
 * of the same job and column counts are not conserved there.
 */
async function findAppCard(page: Page, stages: readonly string[] = APP_STAGES) {
  for (const stage of stages) {
    const column = page.getByTestId(`kanban-column-${stage}`);
    const card = column.getByTestId("application-card").first();
    if ((await card.count()) > 0 && (await card.isVisible())) {
      return { stage, column, card };
    }
  }
  return null;
}

/** App-fed stages whose column counts are conserved under moves. */
const MOVABLE_STAGES = APP_STAGES.filter((s) => s !== "ready");

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

    const found = await findAppCard(page, MOVABLE_STAGES);
    test.skip(!found, "no application cards on the live board to move");
    const { stage: fromStage, card } = found!;
    const title = (await card.getByRole("heading").first().textContent())?.trim() ?? "";
    expect(title).not.toBe("");
    const toStage = MOVABLE_STAGES.find((s) => s !== fromStage)!;
    const fromColumn = page.getByTestId(`kanban-column-${fromStage}`);
    const toColumn = page.getByTestId(`kanban-column-${toStage}`);
    // Live boards can hold several applications with the SAME title (multiple
    // applications for one job), so assert count DELTAS, not absolute zero.
    const countIn = (col: typeof toColumn) =>
      col.getByTestId("application-card").filter({ hasText: title });
    const fromBefore = await countIn(fromColumn).count();
    const toBefore = await countIn(toColumn).count();

    // Move via the accessible menu. ALWAYS await the server response — the
    // count assertions are satisfied by the optimistic UI update within
    // milliseconds, and without this wait the test can end (closing the page
    // and aborting the in-flight fetch) before the move ever hits the server.
    const [moved] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/move") && r.request().method() === "POST"),
      (async () => {
        await card.getByTestId("move-menu-btn").click();
        await card.getByTestId(`move-option-${toStage}`).click();
      })(),
    ]);
    expect(moved.ok()).toBeTruthy();
    await expect(countIn(toColumn)).toHaveCount(toBefore + 1, { timeout: 20_000 });
    await expect(countIn(fromColumn)).toHaveCount(fromBefore - 1);

    // Reload — the move is server-persisted, not client-side sleight of hand.
    await page.reload();
    await expect(page.getByTestId("applications-kanban")).toBeVisible({ timeout: 20_000 });
    await expect(countIn(toColumn)).toHaveCount(toBefore + 1, { timeout: 20_000 });
    await expect(countIn(fromColumn)).toHaveCount(fromBefore - 1);

    // Restore: move the card back to its original stage via the menu.
    const movedCard = countIn(toColumn).first();
    const [restored] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/move") && r.request().method() === "POST"),
      (async () => {
        await movedCard.getByTestId("move-menu-btn").click();
        await movedCard.getByTestId(`move-option-${fromStage}`).click();
      })(),
    ]);
    expect(restored.ok()).toBeTruthy();
    await expect(countIn(fromColumn)).toHaveCount(fromBefore, { timeout: 20_000 });
    await expect(countIn(toColumn)).toHaveCount(toBefore);
  });

  test("drag-and-drop moves a card between columns, then drags it back", async ({
    page,
  }) => {
    await page.goto("/dashboard/applications");
    await expect(page.getByTestId("applications-kanban")).toBeVisible({ timeout: 20_000 });

    const found = await findAppCard(page, MOVABLE_STAGES);
    test.skip(!found, "no application cards on the live board to drag");
    const { stage: fromStage, card } = found!;
    const title = (await card.getByRole("heading").first().textContent())?.trim() ?? "";
    const toStage = MOVABLE_STAGES.find((s) => s !== fromStage)!;
    const fromColumn = page.getByTestId(`kanban-column-${fromStage}`);
    const toColumn = page.getByTestId(`kanban-column-${toStage}`);
    // Duplicate titles are legal on a live board — assert count deltas.
    const countIn = (col: typeof toColumn) =>
      col.getByTestId("application-card").filter({ hasText: title });
    const fromBefore = await countIn(fromColumn).count();
    const toBefore = await countIn(toColumn).count();

    // Drive the HTML5 DnD contract directly (dragstart → dragover → drop with
    // a shared DataTransfer) — mouse-simulation dragTo does not carry
    // dataTransfer payloads into React's onDrop. Each dnd AWAITS the server's
    // /move response: the board updates optimistically, so without the wait a
    // second drag can race the first POST and the moves land out of order.
    const dnd = async (src: typeof card, dst: typeof toColumn) => {
      const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
      const [resp] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/move") && r.request().method() === "POST"),
        (async () => {
          await src.dispatchEvent("dragstart", { dataTransfer });
          await dst.dispatchEvent("dragover", { dataTransfer });
          await dst.dispatchEvent("drop", { dataTransfer });
          await src.dispatchEvent("dragend", { dataTransfer });
        })(),
      ]);
      expect(resp.ok()).toBeTruthy();
    };

    await dnd(card, toColumn);
    await expect(countIn(toColumn)).toHaveCount(toBefore + 1, { timeout: 20_000 });
    await expect(countIn(fromColumn)).toHaveCount(fromBefore - 1);

    // Restore by dragging back.
    await dnd(countIn(toColumn).first(), fromColumn);
    await expect(countIn(fromColumn)).toHaveCount(fromBefore, { timeout: 20_000 });
    await expect(countIn(toColumn)).toHaveCount(toBefore);
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
