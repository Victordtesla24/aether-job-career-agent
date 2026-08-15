// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-2 (c) — the referral link an admin copies has to actually work.
 *
 * RED-first: /signup drops `?ref=` on the floor today.
 *
 * WHY THIS TEST LIVES IN THE FE-2 SLICE. The sales-agents screen hands the
 * operator a link of the form `https://<host>/signup?ref=CODE` to distribute.
 * BE-2 landed the receiving half — `POST /auth/register` accepts `ref` as a
 * body field (or query param) and calls `attribute_signup` — but the signup
 * page never forwarded it, so every referral would have landed, converted, and
 * attributed to nobody. Shipping a copy-this-link button over a client that
 * discards the code is precisely the kind of working-looking dead end this
 * programme forbids, so the pass-through is part of the same slice as the
 * button.
 *
 * ATTRIBUTION MUST NEVER COST THE USER THEIR ACCOUNT. The backend deliberately
 * attributes AFTER the account is committed and swallows a failure there — the
 * account is the user's, the referral credit is the operator's bookkeeping. The
 * client mirrors that ordering by simply passing the code along with the
 * registration it was already making; it adds no second call that could fail.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)}>{children}</a>
  ),
}));

const registerAccountMock = vi.fn();
const loginMock = vi.fn();
vi.mock("../../lib/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/auth")>();
  return {
    ...actual,
    registerAccount: (...a: unknown[]) => registerAccountMock(...a),
    login: (...a: unknown[]) => loginMock(...a),
  };
});

// eslint-disable-next-line import/first
import SignupPage from "../../app/signup/page";

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: "referred@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Passw0rd123" } });
  fireEvent.click(screen.getByLabelText(/terms/i, { selector: "input" }));
  fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
}

beforeEach(() => {
  window.localStorage.clear();
  registerAccountMock.mockResolvedValue({
    id: "u1",
    email: "referred@example.com",
    createdAt: "2026-08-15T00:00:00Z",
  });
  loginMock.mockResolvedValue({
    accessToken: "tok",
    userId: "u1",
    email: "referred@example.com",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/signup");
});

describe("referral pass-through", () => {
  it("forwards ?ref= from the landing URL to the register call", async () => {
    window.history.replaceState({}, "", "/signup?ref=JANE-2026");
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() => expect(registerAccountMock).toHaveBeenCalled());
    expect(registerAccountMock.mock.calls[0]?.[0]).toMatchObject({
      email: "referred@example.com",
      ref: "JANE-2026",
    });
  });

  it("tells the visitor their signup will be attributed", async () => {
    window.history.replaceState({}, "", "/signup?ref=JANE-2026");
    render(<SignupPage />);
    const note = await screen.findByTestId("signup-referral-note");
    expect(note.textContent).toContain("JANE-2026");
  });

  it("sends no ref at all when the visitor arrived without one", async () => {
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() => expect(registerAccountMock).toHaveBeenCalled());
    expect(registerAccountMock.mock.calls[0]?.[0]).not.toHaveProperty("ref");
    expect(screen.queryByTestId("signup-referral-note")).toBeNull();
  });

  it("ignores an empty ref rather than sending a blank attribution", async () => {
    window.history.replaceState({}, "", "/signup?ref=%20%20");
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() => expect(registerAccountMock).toHaveBeenCalled());
    expect(registerAccountMock.mock.calls[0]?.[0]).not.toHaveProperty("ref");
  });

  it("still creates the account when the code is unknown — attribution is not a gate", async () => {
    // The backend attributes after the commit and swallows failures. The client
    // must not add a pre-check that could refuse a real signup over a typo.
    window.history.replaceState({}, "", "/signup?ref=NOT-A-REAL-CODE");
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() => expect(registerAccountMock).toHaveBeenCalled());
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
  });
});
