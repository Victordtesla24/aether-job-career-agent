// @vitest-environment jsdom
/**
 * /signup page (feat/auth-fe FEATURE CONTRACT).
 *
 * RED first: src/app/signup/page.tsx does not exist yet. Renders the real
 * component (as MarketPulse.test.tsx does for its screen) so the defects a
 * backend-only test cannot see — a missing field, a swallowed 409, a
 * validation bypass — are caught at the layer where they'd actually ship.
 *
 * Note: this project does not install @testing-library/jest-dom, so
 * assertions use plain DOM properties/vitest matchers only (no
 * toBeInTheDocument/toHaveAttribute/toHaveValue), matching the existing
 * MarketPulse.test.tsx precedent.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
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
  replaceMock.mockReset();
  registerAccountMock.mockReset();
  loginMock.mockReset();
  window.localStorage.clear();
});

function fillForm({
  name,
  email,
  password,
  consent = true,
}: {
  name?: string;
  email: string;
  password: string;
  consent?: boolean;
}) {
  if (name !== undefined) {
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: name } });
  }
  fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: password } });
  // The Terms/Privacy consent checkbox (MV-terms-001/MV-privacy-policy-001)
  // is required for a real submission; tests that want to reach the API
  // check it by default and opt out explicitly to exercise the block.
  if (consent) {
    fireEvent.click(screen.getByLabelText(/i agree to the/i));
  }
}

describe("SignupPage", () => {
  it("renders name (optional), email, password fields and a Sign in link back to /login", () => {
    render(<SignupPage />);
    expect(screen.getByRole("heading", { name: "Create account", level: 1 }).textContent).toBe("Create account");
    expect(screen.getByLabelText(/name/i)).toBeTruthy();
    expect((screen.getByLabelText(/^email$/i) as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(/^password$/i) as HTMLInputElement).value).toBe("");
    const signInLink = screen.getByRole("link", { name: /sign in/i });
    expect(signInLink.getAttribute("href")).toBe("/login");
  });

  it("blocks submission client-side for a weak password and never calls the API", () => {
    render(<SignupPage />);
    fillForm({ email: "new@example.com", password: "short" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(registerAccountMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/8 characters/);
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

    const errorEl = await screen.findByTestId("signup-error");
    expect(errorEl.textContent).toMatch(/already exists/i);
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

    const errorEl = await screen.findByTestId("signup-error");
    expect(errorEl.textContent).toMatch(/too many attempts/i);
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

  it("MV-terms-001/MV-privacy-policy-001: renders a Terms/Privacy consent checkbox linking to both pages", () => {
    render(<SignupPage />);
    const checkbox = screen.getByLabelText(/i agree to the/i) as HTMLInputElement;
    expect(checkbox.type).toBe("checkbox");
    expect(checkbox.checked).toBe(false);

    // "Terms & Conditions" only appears in the consent line, so this is
    // unambiguous even though the page's footer separately links "Terms".
    const termsLink = screen.getByRole("link", { name: /terms & conditions/i });
    expect(termsLink.getAttribute("href")).toBe("/terms");

    // "Privacy Policy" appears both in the consent line and the footer —
    // assert every instance points at the right page.
    const privacyLinks = screen.getAllByRole("link", { name: /privacy policy/i });
    expect(privacyLinks.length).toBeGreaterThanOrEqual(1);
    for (const link of privacyLinks) {
      expect(link.getAttribute("href")).toBe("/privacy-policy");
    }
  });

  it("MV-terms-001/MV-privacy-policy-001: blocks submission and never calls the API when consent is not checked", () => {
    render(<SignupPage />);
    fillForm({ email: "new@example.com", password: "abcdefg1", consent: false });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(registerAccountMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/agree to the terms/i);
  });

  it("MV-terms-001/MV-privacy-policy-001: proceeds once the consent checkbox is checked", async () => {
    registerAccountMock.mockResolvedValue({ id: "u1", email: "new@example.com", createdAt: "2026-07-14T00:00:00" });
    loginMock.mockResolvedValue({ accessToken: "jwt-abc", userId: "u1", email: "new@example.com" });

    render(<SignupPage />);
    fillForm({ email: "new@example.com", password: "abcdefg1", consent: true });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(registerAccountMock).toHaveBeenCalled());
  });

  it("MV-privacy-policy-001/MV-terms-001: shows a dedicated footer with a bare 'Terms' link (distinct from the consent line)", () => {
    render(<SignupPage />);
    const footerTermsLink = screen.getByRole("link", { name: /^terms$/i });
    expect(footerTermsLink.getAttribute("href")).toBe("/terms");
    expect(screen.getByTestId("public-legal-footer")).not.toBeNull();
  });

  it("MV-signup-002: redirects an already-authenticated visitor to /dashboard instead of showing the form", () => {
    window.localStorage.setItem("aether_token", "jwt-123");
    render(<SignupPage />);
    expect(replaceMock).toHaveBeenCalledWith("/dashboard");
    expect(screen.queryByRole("heading", { name: "Create account", level: 1 })).toBeNull();
  });
});
