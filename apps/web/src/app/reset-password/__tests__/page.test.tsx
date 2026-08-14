// @vitest-environment jsdom
/**
 * /reset-password?token=... — O-4 self-service password reset completion
 * (S-FIX slice D).
 *
 * RED first. ``token`` is read from ``window.location.search`` client-side
 * (mirrors /login's convention), so each test sets it via
 * ``window.history.replaceState`` before rendering.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const resetPasswordMock = vi.fn();
vi.mock("../../../lib/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/auth")>();
  return {
    ...actual,
    resetPassword: (...args: unknown[]) => resetPasswordMock(...args),
  };
});

// eslint-disable-next-line import/first
import { AuthApiError } from "../../../lib/api/auth";
// eslint-disable-next-line import/first
import ResetPasswordPage from "../page";

afterEach(() => {
  cleanup();
  resetPasswordMock.mockReset();
  window.history.replaceState(null, "", "/reset-password");
});

describe("ResetPasswordPage", () => {
  it("shows a missing-token message when no ?token= is present", async () => {
    render(<ResetPasswordPage />);
    await waitFor(() => expect(screen.getByTestId("reset-password-missing-token")).toBeTruthy());
    expect(screen.queryByLabelText(/new password/i)).toBeFalsy();
    expect(screen.getByRole("link", { name: /request a new one/i }).getAttribute("href")).toBe(
      "/forgot-password",
    );
  });

  it("renders the new-password form when a token is present", async () => {
    window.history.replaceState(null, "", "/reset-password?token=abc123");
    render(<ResetPasswordPage />);
    await waitFor(() => expect(screen.getByLabelText(/^new password$/i)).toBeTruthy());
    expect(screen.getByLabelText(/confirm new password/i)).toBeTruthy();
  });

  it("rejects a mismatched confirmation before calling the API", async () => {
    window.history.replaceState(null, "", "/reset-password?token=abc123");
    render(<ResetPasswordPage />);
    await waitFor(() => expect(screen.getByLabelText(/^new password$/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/^new password$/i), { target: { value: "NewPassw0rd1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "Different1" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() => expect(screen.getByTestId("reset-password-error")).toBeTruthy());
    expect(screen.getByTestId("reset-password-error").textContent).toMatch(/do not match/i);
    expect(resetPasswordMock).not.toHaveBeenCalled();
  });

  it("submits token + password and shows success on 200", async () => {
    resetPasswordMock.mockResolvedValue(undefined);
    window.history.replaceState(null, "", "/reset-password?token=the-real-token");
    render(<ResetPasswordPage />);
    await waitFor(() => expect(screen.getByLabelText(/^new password$/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/^new password$/i), { target: { value: "NewPassw0rd1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "NewPassw0rd1" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() => expect(screen.getByTestId("reset-password-success")).toBeTruthy());
    expect(resetPasswordMock).toHaveBeenCalledWith("the-real-token", "NewPassw0rd1");
    expect(screen.getByRole("link", { name: /go to sign in/i }).getAttribute("href")).toBe("/login");
  });

  it("shows an inline error for an invalid/expired token (400)", async () => {
    resetPasswordMock.mockRejectedValue(
      new AuthApiError("This reset link is invalid or has expired. Request a new one.", 400),
    );
    window.history.replaceState(null, "", "/reset-password?token=expired-token");
    render(<ResetPasswordPage />);
    await waitFor(() => expect(screen.getByLabelText(/^new password$/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/^new password$/i), { target: { value: "NewPassw0rd1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "NewPassw0rd1" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() => expect(screen.getByTestId("reset-password-error")).toBeTruthy());
    expect(screen.getByTestId("reset-password-error").textContent).toMatch(/invalid or has expired/i);
  });

  it("shows the config-managed refusal instead of a false success (§14.7)", async () => {
    // The API refuses a reset for the env-managed admin identity, because the
    // §14.7 rotation re-applies AETHER_ADMIN_PASSWORD_HASH on every restart and
    // would silently revert it. The page must render that reason and must NOT
    // show the "Your password has been reset" success state.
    resetPasswordMock.mockRejectedValue(
      new AuthApiError(
        "This account's password is managed by server configuration " +
          "(AETHER_ADMIN_PASSWORD_HASH) and is re-applied every time the API restarts.",
        409,
      ),
    );
    window.history.replaceState(null, "", "/reset-password?token=owner-token");
    render(<ResetPasswordPage />);
    await waitFor(() => expect(screen.getByLabelText(/^new password$/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/^new password$/i), { target: { value: "NewPassw0rd1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "NewPassw0rd1" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() => expect(screen.getByTestId("reset-password-error")).toBeTruthy());
    expect(screen.getByTestId("reset-password-error").textContent).toMatch(
      /managed by server configuration/i,
    );
    expect(screen.queryByTestId("reset-password-success")).toBeFalsy();
  });
});
