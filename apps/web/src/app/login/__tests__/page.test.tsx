// @vitest-environment jsdom
/**
 * /login page relabel + create-account link (feat/auth-fe FEATURE CONTRACT).
 *
 * RED first: before this change the field was labelled plain "Email" (an
 * <input type="email">, which rejects a bare username like "admin" via
 * native HTML5 validation even though the backend accepts username-or-email)
 * and there was no link to /signup. Renders the real component so the
 * mislabel/missing-link defects are caught at the layer where they'd ship.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
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
  loginMock.mockReset();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/login");
});

describe("LoginPage", () => {
  it('labels the identifier field "Email or username" and accepts a bare username', () => {
    render(<LoginPage />);
    const field = screen.getByLabelText(/email or username/i);
    expect(field).toBeInTheDocument();
    // A plain <input type="email"> would reject a bare username under HTML5
    // constraint validation — the field must NOT be type="email".
    expect(field).not.toHaveAttribute("type", "email");
  });

  it("links to /signup to create an account", () => {
    render(<LoginPage />);
    const createAccountLink = screen.getByRole("link", { name: /create account/i });
    expect(createAccountLink).toHaveAttribute("href", "/signup");
  });

  it("still renders the Sign in heading and empty fields", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: "Sign in", level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText(/email or username/i)).toHaveValue("");
    expect(screen.getByLabelText(/^password$/i)).toHaveValue("");
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

    expect(await screen.findByTestId("login-error")).toHaveTextContent(/too many failed login attempts/i);
  });

  it("shows a success flash when arriving with ?registered=1 (post-signup fallback)", async () => {
    window.history.replaceState(null, "", "/login?registered=1");
    render(<LoginPage />);
    expect(await screen.findByTestId("signup-success")).toHaveTextContent(/account created/i);
  });
});
