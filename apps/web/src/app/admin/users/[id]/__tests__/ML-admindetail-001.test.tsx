// @vitest-environment jsdom
/**
 * ML-admindetail-001 (MEDIUM) — /admin/users/[id]: clearing the spend-cap
 * input and saving SILENTLY persists a $0.00 cap with a SUCCESS notice
 * (uat/reports/evidence/models-live/screens/admin-user-detail/
 * TESTING-OUTCOME-REPORT.md; confirmed live via AdminAuditLog rows).
 *
 * RCA (verified against current code, apps/web/src/app/admin/users/[id]/
 * page.tsx `onSaveCap`):
 *
 *   const value = Number(capInput);
 *   if (!Number.isFinite(value) || value < 0) { ...reject... }
 *
 * `Number("")` (and `Number("   ")`) coerces to `0`, which is finite and
 * `>= 0`, so the guard PASSES for an empty/blank field exactly as it would
 * for a deliberately-typed "0" — the component can no longer tell the two
 * apart once `Number()` has run. `setSpendCap(userId, 0)` is then called and
 * succeeds, so the admin sees "Spend cap set to $0.00." with no indication
 * anything went wrong.
 *
 * The backend is NOT the bug: `SpendCapRequest.spendCapUsd: float =
 * Field(ge=0)` (apps/api/app/routers/admin.py) has no default and Pydantic
 * already 422s on missing/None/empty-string/non-numeric bodies (verified
 * directly against the live model — `{}`, `{"spendCapUsd": null}\`,
 * `{"spendCapUsd": ""}` all raise `ValidationError`; `apps/api/tests/
 * test_gap_p6_admin.py` already pins malformed/negative/wrong-type 422s).
 * By the time a request reaches the backend the empty field has ALREADY
 * been coerced to the legitimate float `0` client-side, so the backend has
 * no way to distinguish "admin cleared the field" from "admin typed 0" —
 * only the frontend, which still holds the raw string, can make that call.
 * This spec therefore pins the contract at the FE layer only.
 *
 * NUANCE for the fixer: the bug is EMPTY silently becoming 0, not 0 itself.
 * An admin who explicitly types "0" is expressing a real, deliberate choice
 * (a zero spend cap) and that must keep saving successfully — the fix must
 * reject a blank/whitespace-only field specifically (e.g. check
 * `capInput.trim() === ""` BEFORE calling `Number()`), not forbid the
 * numeric value 0. The third test below pins that boundary as a regression
 * guard and already PASSES against current code — only the first two
 * (empty / whitespace-only) are expected to fail before the fix.
 *
 * This project does not install @testing-library/jest-dom, so assertions use
 * plain DOM properties / vitest matchers only (matches sibling test files).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useParamsMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => useParamsMock(),
}));

const fetchAdminUserMock = vi.fn();
const setSpendCapMock = vi.fn();
const setSuspendedMock = vi.fn();
vi.mock("../../../../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../../lib/api/admin")>();
  return {
    ...actual,
    fetchAdminUser: (...args: unknown[]) => fetchAdminUserMock(...args),
    setSpendCap: (...args: unknown[]) => setSpendCapMock(...args),
    setSuspended: (...args: unknown[]) => setSuspendedMock(...args),
  };
});

// eslint-disable-next-line import/first
import AdminUserDetailPage from "../page";

const USER_ID = "user-abc-123";

const DETAIL = {
  user: {
    id: USER_ID,
    email: "jamie@example.com",
    name: "Jamie Rivera",
    isAdmin: false,
    suspended: false,
    plan: "pro",
    subStatus: "active",
    signupAt: "2026-01-01T00:00:00Z",
    lastLoginAt: "2026-07-01T00:00:00Z",
    spendUsd: 4.2,
    runCount: 3,
    currency: "USD",
  },
  subscription: null,
  quota: {
    planId: "pro",
    runsUsed: 3,
    runsAllowed: 100,
    spendUsedUsd: 4.2,
    spendCapUsd: 15,
    periodEnd: "2026-08-01T00:00:00Z",
    currency: "USD",
  },
  recentRuns: [],
  spendUsd: 4.2,
  runCount: 3,
  currency: "USD",
};

async function renderLoaded() {
  render(<AdminUserDetailPage />);
  const input = await screen.findByRole("textbox");
  await waitFor(() => expect(fetchAdminUserMock).toHaveBeenCalled());
  return input;
}

afterEach(() => {
  cleanup();
  useParamsMock.mockReset();
  fetchAdminUserMock.mockReset();
  setSpendCapMock.mockReset();
  setSuspendedMock.mockReset();
});

describe("ML-admindetail-001: empty spend-cap must NOT silently save as $0.00", () => {
  it("rejects an emptied spend-cap field with a validation error and never calls setSpendCap", async () => {
    useParamsMock.mockReturnValue({ id: USER_ID });
    fetchAdminUserMock.mockResolvedValue(DETAIL);

    const input = await renderLoaded();
    expect((input as HTMLInputElement).value).toBe("15");

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save cap/i }));

    // Give the (buggy) async handler a tick to run so a false-positive
    // network call / success notice has a chance to appear.
    await waitFor(() => expect(screen.queryByRole("button", { name: /save cap/i })).toBeTruthy());

    expect(
      setSpendCapMock,
      "setSpendCap was called for an EMPTY field — Number('') coerced to 0 and " +
        "slipped past the >=0 guard, silently persisting a $0.00 cap",
    ).not.toHaveBeenCalled();

    const successNotice = document.querySelector("p.text-aether-green");
    expect(
      successNotice?.textContent ?? null,
      "a success notice was shown for an EMPTY field save — this is exactly " +
        "the silent-$0.00-with-SUCCESS defect",
    ).toBeNull();

    const errorEl = document.querySelector("p.text-sm.text-red-300");
    expect(
      errorEl?.textContent ?? null,
      "no validation error was shown for an EMPTY spend-cap field — the admin " +
        "gets no honest feedback that clearing the field is not a no-op",
    ).not.toBeNull();
  });

  it("rejects a whitespace-only spend-cap field the same as empty", async () => {
    useParamsMock.mockReturnValue({ id: USER_ID });
    fetchAdminUserMock.mockResolvedValue(DETAIL);

    const input = await renderLoaded();

    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /save cap/i }));

    await waitFor(() => expect(screen.queryByRole("button", { name: /save cap/i })).toBeTruthy());

    expect(
      setSpendCapMock,
      "setSpendCap was called for a WHITESPACE-ONLY field — Number('   ') also " +
        "coerces to 0 and slips past the >=0 guard",
    ).not.toHaveBeenCalled();

    const errorEl = document.querySelector("p.text-sm.text-red-300");
    expect(errorEl?.textContent ?? null).not.toBeNull();
  });

  it("[regression guard] an explicit 0 the admin deliberately types still saves successfully", async () => {
    useParamsMock.mockReturnValue({ id: USER_ID });
    fetchAdminUserMock.mockResolvedValue(DETAIL);
    setSpendCapMock.mockResolvedValue({ userId: USER_ID, spendCapUsd: 0, currency: "USD" });

    const input = await renderLoaded();

    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /save cap/i }));

    await waitFor(() => expect(setSpendCapMock).toHaveBeenCalledWith(USER_ID, 0));

    const successNotice = await waitFor(() => {
      const el = document.querySelector("p.text-aether-green");
      if (!el) throw new Error("success notice not rendered yet");
      return el;
    });
    expect(successNotice.textContent ?? "").toMatch(/\$0\.00/);
  });
});
