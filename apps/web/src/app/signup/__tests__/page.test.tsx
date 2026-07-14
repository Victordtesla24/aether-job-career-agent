// @vitest-environment jsdom
/**
 * /signup page (feat/auth-fe FEATURE CONTRACT).
 *
 * RED first: src/app/signup/page.tsx does not exist yet. Renders the real
 * component (as MarketPulse.test.tsx does for its screen) so the defects a
 * backend-only test cannot see — a missing field, a swallowed 409, a
 * validation bypass — are caught at the layer where they'd actually ship.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const registerAccountMock = vi.fn();
const loginMock = vi.fn();
vi.mock("../../../lib/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/auth")>();
  return {
    ...actual,
    registerAccount: (...args: unknown[]) => registerAccountMock(...args),
    login: (...args: unknown[]) => loginMock(...args),
  };
});

// eslint-disable-next-line import/first
import { AuthApiError } from "../../../lib/api/auth";
// eslint-disable-next-line import/first
import SignupPage from "../page";

afterEach(() => {
  cleanup();
  pushMock.mockReset();
  registerAccountMock.mockReset();
  loginMock.mockReset();
  window.localStorage.clear();
});

function fillForm({ name, email, password }: { name?: string; email: string; password: string }) {
  if (name !== undefined) {
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: name } });
  }
  fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: password } });
}

describe("SignupPage", () => {
  it("renders name (optional), email, password fields and a Sign in link back to /login", () => {
    render(<SignupPage />);
    expect(screen.getByRole("heading", { name: "Create account", level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    const signInLink = screen.getByRole("link", { name: /sign in/i });
    expect(signInLink).toHaveAttribute("href", "/login");
  });

  it("blocks submission client-side for a weak password and never calls the API", () => {
    render(<SignupPage />);
    fillForm({ email: "new@example.com", password: "short" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(registerAccountMock).not.toHaveBeenCalled();
    expect(screen.getByText(/8 characters/)).toBeInTheDocument();
  });

  it("registers, auto-logs in, stores the token, and routes to /dashboard on success", async () => {
    registerAccountMock.mockResolvedValue({ id: "u1", email: "new@example.com", createdAt: "2026-07-14T00:00:00" });
    loginMock.mockResolvedValue({ accessToken: "jwt-abc", userId: "u1", email: "new@example.com" });

    render(<SignupPage />);
    fillForm({ name: "Ada Lovelace", email: "new@example.com", password: "abcdefg1" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
    expect(registerAccountMock).toHaveBeenCalledWith({
      email: "new@example.com",
      password: "abcdefg1",
      name: "Ada Lovelace",
    });
    expect(loginMock).toHaveBeenCalledWith("new@example.com", "abcdefg1");
    expect(window.localStorage.getItem("aether_token")).toBe("jwt-abc");
  });

  it("shows an honest 409 message on a duplicate email and does not attempt login", async () => {
    registerAccountMock.mockRejectedValue(new AuthApiError("An account with this email already exists.", 409));

    render(<SignupPage />);
    fillForm({ email: "dup@example.com", password: "abcdefg1" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByTestId("signup-error")).toHaveTextContent(/already exists/i);
    expect(loginMock).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("shows an honest 429 rate-limit message", async () => {
    registerAccountMock.mockRejectedValue(
      new AuthApiError("Too many attempts. Please wait and try again. Try again in 3600s.", 429, 3600),
    );

    render(<SignupPage />);
    fillForm({ email: "spam@example.com", password: "abcdefg1" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByTestId("signup-error")).toHaveTextContent(/too many attempts/i);
  });

  it("falls back to /login with a success flash if the account was created but auto-login fails", async () => {
    registerAccountMock.mockResolvedValue({ id: "u1", email: "new@example.com", createdAt: "2026-07-14T00:00:00" });
    loginMock.mockRejectedValue(new AuthApiError("Invalid email or password.", 401));

    render(<SignupPage />);
    fillForm({ email: "new@example.com", password: "abcdefg1" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/login?registered=1"));
    expect(window.localStorage.getItem("aether_token")).toBeNull();
  });
});
