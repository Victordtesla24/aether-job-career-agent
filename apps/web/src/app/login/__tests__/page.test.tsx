// @vitest-environment jsdom
/**
 * /login page relabel + create-account link (feat/auth-fe FEATURE CONTRACT).
 *
 * RED first: before this change the field was labelled plain "Email" (an
 * <input type="email">, which rejects a bare username like "admin" via
 * native HTML5 validation even though the backend accepts username-or-email)
 * and there was no link to /signup. Renders the real component so the
 * mislabel/missing-link defects are caught at the layer where they'd ship.
 *
 * Note: this project does not install @testing-library/jest-dom, so
 * assertions use plain DOM properties/vitest matchers only.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
}));

const loginMock = vi.fn();
vi.mock("../../../lib/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/auth")>();
  return {
    ...actual,
    login: (...args: unknown[]) => loginMock(...args),
  };
});

// eslint-disable-next-line import/first
import { AuthApiError } from "../../../lib/api/auth";
// eslint-disable-next-line import/first
import LoginPage from "../page";

afterEach(() => {
  cleanup();
  pushMock.mockReset();
  replaceMock.mockReset();
  loginMock.mockReset();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/login");
});

describe("LoginPage", () => {
  it('labels the identifier field "Email or username" and accepts a bare username', () => {
    render(<LoginPage />);
    const field = screen.getByLabelText(/email or username/i) as HTMLInputElement;
    expect(field).toBeTruthy();
    // A plain <input type="email"> would reject a bare username under HTML5
    // constraint validation — the field must NOT be type="email".
    expect(field.type).not.toBe("email");
  });

  it("links to /signup to create an account", () => {
    render(<LoginPage />);
    const createAccountLink = screen.getByRole("link", { name: /create account/i });
    expect(createAccountLink.getAttribute("href")).toBe("/signup");
  });

  it("still renders the Sign in heading and empty fields", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: "Sign in", level: 1 }).textContent).toBe("Sign in");
    expect((screen.getByLabelText(/email or username/i) as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(/^password$/i) as HTMLInputElement).value).toBe("");
  });

  it("logs in with a bare username identifier and redirects to /dashboard", async () => {
    loginMock.mockResolvedValue({ accessToken: "jwt-admin", userId: "u0", email: "admin@aether.local" });

    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "admin123" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
    expect(loginMock).toHaveBeenCalledWith("admin", "admin123");
    expect(window.localStorage.getItem("aether_token")).toBe("jwt-admin");
  });

  it("shows an honest 429 lockout message instead of a generic failure", async () => {
    loginMock.mockRejectedValue(
      new AuthApiError("Too many failed login attempts for this account. Please wait and try again.", 429, 900),
    );

    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const errorEl = await screen.findByTestId("login-error");
    expect(errorEl.textContent).toMatch(/too many failed login attempts/i);
  });

  it("shows a success flash when arriving with ?registered=1 (post-signup fallback)", async () => {
    window.history.replaceState(null, "", "/login?registered=1");
    render(<LoginPage />);
    const flash = await screen.findByTestId("signup-success");
    expect(flash.textContent).toMatch(/account created/i);
  });

  it("MV-privacy-policy-001/MV-terms-001: shows a footer linking to /privacy-policy and /terms", () => {
    render(<LoginPage />);
    const privacyLink = screen.getByRole("link", { name: /privacy policy/i });
    const termsLink = screen.getByRole("link", { name: /^terms$/i });
    expect(privacyLink.getAttribute("href")).toBe("/privacy-policy");
    expect(termsLink.getAttribute("href")).toBe("/terms");
  });

  it("MV-login-001: redirects an already-authenticated visitor to /dashboard instead of showing the form", () => {
    window.localStorage.setItem("aether_token", "jwt-123");
    render(<LoginPage />);
    expect(replaceMock).toHaveBeenCalledWith("/dashboard");
    expect(screen.queryByRole("heading", { name: "Sign in", level: 1 })).toBeNull();
  });

  it("MV-login-002: returns an authenticated visitor to a safe ?next destination", () => {
    window.history.replaceState(null, "", "/login?next=" + encodeURIComponent("/dashboard/jobs"));
    window.localStorage.setItem("aether_token", "jwt-123");
    render(<LoginPage />);
    expect(replaceMock).toHaveBeenCalledWith("/dashboard/jobs");
  });

  it("MV-login-002: honors a safe ?next path after a successful login", async () => {
    loginMock.mockResolvedValue({ accessToken: "jwt-x", userId: "u1", email: "a@example.com" });
    window.history.replaceState(null, "", "/login?next=" + encodeURIComponent("/dashboard/jobs"));
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "pw1234567" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard/jobs"));
  });

  it("MV-login-004: offers an honest Forgot password link to /forgot-password", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: /forgot password/i });
    expect(link.getAttribute("href")).toBe("/forgot-password");
  });
});
