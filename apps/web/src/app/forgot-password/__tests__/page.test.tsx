// @vitest-environment jsdom
/**
 * /forgot-password — O-4 self-service password reset (S-FIX slice D).
 *
 * RED first: exercises the real client component. Covers both honest states
 * driven by the backend's ``emailSendingEnabled`` flag, plus the rate-limit /
 * generic-error paths.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const forgotPasswordMock = vi.fn();
vi.mock("../../../lib/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/auth")>();
  return {
    ...actual,
    forgotPassword: (...args: unknown[]) => forgotPasswordMock(...args),
  };
});

// eslint-disable-next-line import/first
import { AuthApiError } from "../../../lib/api/auth";
// eslint-disable-next-line import/first
import ForgotPasswordClient from "../forgot-password-client";

afterEach(() => {
  cleanup();
  forgotPasswordMock.mockReset();
});

describe("ForgotPasswordClient", () => {
  it("renders an email form by default", () => {
    render(<ForgotPasswordClient supportEmail="help@aether.example" supportPhone={null} />);
    expect(screen.getByRole("heading", { name: "Reset your password" })).toBeTruthy();
    expect(screen.getByLabelText(/^email$/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /send reset link/i })).toBeTruthy();
  });

  it("shows the honest 'sent' state when the backend reports emailSendingEnabled=true", async () => {
    forgotPasswordMock.mockResolvedValue({ ok: true, emailSendingEnabled: true, deliveryDegraded: false });
    render(<ForgotPasswordClient supportEmail="help@aether.example" supportPhone={null} />);

    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "user@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByTestId("forgot-password-sent")).toBeTruthy());
    expect(forgotPasswordMock).toHaveBeenCalledWith("user@example.com");
    expect(screen.queryByTestId("forgot-password-not-configured")).toBeFalsy();
    expect(screen.queryByTestId("forgot-password-degraded")).toBeFalsy();
  });

  it("MF-3: does NOT claim success when the backend reports deliveryDegraded=true, even though emailSendingEnabled is true", async () => {
    forgotPasswordMock.mockResolvedValue({ ok: true, emailSendingEnabled: true, deliveryDegraded: true });
    render(<ForgotPasswordClient supportEmail="help@aether.example" supportPhone={null} />);

    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "user@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByTestId("forgot-password-degraded")).toBeTruthy());
    // The banned optimistic-success pattern: must never render the fake "sent" copy.
    expect(screen.queryByTestId("forgot-password-sent")).toBeFalsy();
    const degraded = screen.getByTestId("forgot-password-degraded");
    expect(degraded.textContent).toContain("help@aether.example");
  });

  it("shows the honest 'not configured' + support-contact state when emailSendingEnabled=false", async () => {
    forgotPasswordMock.mockResolvedValue({ ok: true, emailSendingEnabled: false });
    render(<ForgotPasswordClient supportEmail="help@aether.example" supportPhone={null} />);

    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "user@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByTestId("forgot-password-not-configured")).toBeTruthy());
    // Never claims an email was sent.
    expect(screen.queryByTestId("forgot-password-sent")).toBeFalsy();
    const notConfigured = screen.getByTestId("forgot-password-not-configured");
    expect(notConfigured.textContent).toContain("help@aether.example");
  });

  it("falls back to the Terms link when no support email is configured", async () => {
    forgotPasswordMock.mockResolvedValue({ ok: true, emailSendingEnabled: false });
    render(<ForgotPasswordClient supportEmail={null} supportPhone={null} />);

    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "user@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByTestId("forgot-password-not-configured")).toBeTruthy());
    const notConfigured = screen.getByTestId("forgot-password-not-configured");
    expect(notConfigured.querySelector('a[href="/terms"]')).toBeTruthy();
  });

  it("shows a rate-limit error message inline without leaving the form", async () => {
    forgotPasswordMock.mockRejectedValue(new AuthApiError("Too many attempts. Please wait and try again.", 429, 60));
    render(<ForgotPasswordClient supportEmail="help@aether.example" supportPhone={null} />);

    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "user@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByTestId("forgot-password-error")).toBeTruthy());
    expect(screen.getByTestId("forgot-password-error").textContent).toMatch(/too many attempts/i);
    // The form itself is still present — never silently swapped for the "sent" state on error.
    expect(screen.getByLabelText(/^email$/i)).toBeTruthy();
  });

  it("links back to /login", () => {
    render(<ForgotPasswordClient supportEmail={null} supportPhone={null} />);
    const backLink = screen.getAllByRole("link", { name: /back to sign in/i })[0];
    expect(backLink.getAttribute("href")).toBe("/login");
  });
});
