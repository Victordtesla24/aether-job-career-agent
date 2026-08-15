// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-2 (a) — the Add-user modal on /admin/users.
 *
 * RED-first: neither the button nor the modal exists in this tree yet.
 *
 * THE ONE INVARIANT THIS FILE EXISTS TO PIN. `POST /admin/users` returns a
 * generated temporary password EXACTLY ONCE — BE-1's route hashes it, never
 * stores it, never audits it, and there is no second endpoint that can read it
 * back. A modal that shows that value without saying so, or that closes it
 * behind an accidental click, silently costs the admin the credential and the
 * new account with it. So the specs below pin three things together: the value
 * is rendered, it is rendered WITH the "shown once" warning, and the only way
 * past it is a deliberate acknowledgement.
 *
 * The second invariant is the ordinary one: a 409 (duplicate email) is the
 * backend refusing honestly, and must reach the admin in the backend's own
 * words rather than as "something went wrong".
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../lib/api/client";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)}>{children}</a>
  ),
}));

const fetchAdminUsersMock = vi.fn();
const createAdminUserMock = vi.fn();

vi.mock("../../../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/admin")>();
  return {
    ...actual,
    fetchAdminUsers: (...a: unknown[]) => fetchAdminUsersMock(...a),
    createAdminUser: (...a: unknown[]) => createAdminUserMock(...a),
  };
});

// eslint-disable-next-line import/first
import AdminUsersPage from "../page";

const TEMP_PASSWORD = "Tk7#qLm2Xw9Z";

function emptyList() {
  return { users: [], total: 0, limit: 100, offset: 0 };
}

async function renderPage() {
  fetchAdminUsersMock.mockResolvedValue(emptyList());
  render(<AdminUsersPage />);
  await waitFor(() => expect(fetchAdminUsersMock).toHaveBeenCalled());
}

async function openModal() {
  await renderPage();
  fireEvent.click(screen.getByTestId("admin-add-user"));
  await screen.findByTestId("admin-add-user-dialog");
}

async function createOne(email = "newbie@example.com", name = "New Bie") {
  await openModal();
  createAdminUserMock.mockResolvedValue({
    userId: "user-new-1",
    email,
    name,
    tempPassword: TEMP_PASSWORD,
    mustChangePassword: true,
    createdAt: "2026-08-15T00:00:00Z",
  });
  fireEvent.change(screen.getByLabelText("New user email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("New user name (optional)"), {
    target: { value: name },
  });
  fireEvent.click(screen.getByTestId("admin-add-user-submit"));
  await screen.findByTestId("admin-temp-password");
}

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("add-user modal", () => {
  it("sends the email and name the admin typed", async () => {
    await createOne("jo@example.com", "Jo Smith");
    expect(createAdminUserMock).toHaveBeenCalledTimes(1);
    expect(createAdminUserMock.mock.calls[0]?.[0]).toEqual({
      email: "jo@example.com",
      name: "Jo Smith",
    });
  });

  it("omits an empty name rather than sending a blank one", async () => {
    await openModal();
    createAdminUserMock.mockResolvedValue({
      userId: "u2",
      email: "solo@example.com",
      name: null,
      tempPassword: TEMP_PASSWORD,
      mustChangePassword: true,
      createdAt: null,
    });
    fireEvent.change(screen.getByLabelText("New user email"), {
      target: { value: "solo@example.com" },
    });
    fireEvent.click(screen.getByTestId("admin-add-user-submit"));

    await screen.findByTestId("admin-temp-password");
    expect(createAdminUserMock.mock.calls[0]?.[0]).toEqual({ email: "solo@example.com" });
  });

  it("refuses to submit without an email, and never calls the API", async () => {
    await openModal();
    fireEvent.click(screen.getByTestId("admin-add-user-submit"));
    await waitFor(() => expect(screen.getByTestId("admin-add-user-error")).toBeTruthy());
    expect(createAdminUserMock).not.toHaveBeenCalled();
  });
});

describe("the one-time temporary password", () => {
  it("shows the generated password with an explicit shown-once warning", async () => {
    await createOne();
    expect(screen.getByTestId("admin-temp-password").textContent).toContain(TEMP_PASSWORD);
    const warning = screen.getByTestId("admin-temp-password-warning").textContent ?? "";
    expect(warning).toMatch(/once/i);
    // The remedy when it is lost must be stated, not left for the admin to guess.
    expect(warning).toMatch(/set a new password|cannot be (shown|retrieved)/i);
  });

  it("copies the password to the clipboard on demand", async () => {
    await createOne();
    fireEvent.click(screen.getByTestId("admin-temp-password-copy"));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(TEMP_PASSWORD),
    );
  });

  it("says so honestly when the clipboard is blocked instead of claiming a copy", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    await createOne();
    fireEvent.click(screen.getByTestId("admin-temp-password-copy"));
    await waitFor(() => {
      const state = screen.getByTestId("admin-temp-password-copy").textContent ?? "";
      expect(state).not.toMatch(/^copied/i);
      expect(state).toMatch(/couldn|manual/i);
    });
    // The value stays on screen so it can still be selected by hand.
    expect(screen.getByTestId("admin-temp-password").textContent).toContain(TEMP_PASSWORD);
  });

  it("keeps the password on screen until the admin acknowledges it", async () => {
    await createOne();
    // No stray close affordance may dismiss the credential — only the explicit
    // acknowledgement does, and the form is gone while it is displayed.
    expect(screen.queryByLabelText("New user email")).toBeNull();
    fireEvent.click(screen.getByTestId("admin-add-user-done"));
    await waitFor(() => expect(screen.queryByTestId("admin-add-user-dialog")).toBeNull());
    expect(document.body.textContent).not.toContain(TEMP_PASSWORD);
  });

  it("reloads the user list once the account exists", async () => {
    await createOne();
    fireEvent.click(screen.getByTestId("admin-add-user-done"));
    await waitFor(() => expect(fetchAdminUsersMock.mock.calls.length).toBeGreaterThan(1));
  });
});

describe("refusals reach the admin verbatim", () => {
  it("surfaces a duplicate-email 409 in the backend's own words", async () => {
    await openModal();
    createAdminUserMock.mockRejectedValue(
      new ApiError("That email is already registered.", 409),
    );
    fireEvent.change(screen.getByLabelText("New user email"), {
      target: { value: "taken@example.com" },
    });
    fireEvent.click(screen.getByTestId("admin-add-user-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("admin-add-user-error").textContent).toContain(
        "That email is already registered.",
      ),
    );
    // A failed create must not leave a password panel behind.
    expect(screen.queryByTestId("admin-temp-password")).toBeNull();
  });
});

describe("the list shows soft-deleted accounts as deleted", () => {
  it("flags a deleted row instead of hiding it", async () => {
    fetchAdminUsersMock.mockResolvedValue({
      users: [
        {
          id: "u-del",
          email: "gone@example.com",
          name: "Gone Away",
          username: null,
          isAdmin: false,
          suspended: true,
          deletedAt: "2026-08-14T00:00:00Z",
          mustChangePassword: false,
          plan: "free",
          subStatus: "canceled",
          signupAt: "2026-01-01T00:00:00Z",
          lastLoginAt: null,
          spendUsd: 0,
          runCount: 0,
          currency: "USD",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    render(<AdminUsersPage />);
    const row = await screen.findByTestId("admin-user-row-u-del");
    expect(row.textContent).toMatch(/deleted/i);
  });
});
