// @vitest-environment jsdom
/**
 * Sales AI first-touch: `/signup?utm_source=aether_sales_agent` must reach
 * POST /auth/register. Absence is absence; a bad value is the API's to ignore.
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
    target: { value: "utm@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Passw0rd123" } });
  fireEvent.click(screen.getByLabelText(/terms/i, { selector: "input" }));
  fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
}

beforeEach(() => {
  window.localStorage.clear();
  registerAccountMock.mockResolvedValue({
    id: "u1",
    email: "utm@example.com",
    createdAt: "2026-08-18T00:00:00Z",
  });
  loginMock.mockResolvedValue({
    accessToken: "tok",
    userId: "u1",
    email: "utm@example.com",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/signup");
});

describe("utm_source pass-through", () => {
  it("forwards ?utm_source= from the landing URL to the register call", async () => {
    window.history.replaceState({}, "", "/signup?utm_source=aether_sales_agent");
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() => expect(registerAccountMock).toHaveBeenCalled());
    expect(registerAccountMock.mock.calls[0]?.[0]).toMatchObject({
      email: "utm@example.com",
      utmSource: "aether_sales_agent",
    });
  });

  it("sends no utmSource when the visitor arrived without one", async () => {
    render(<SignupPage />);
    fillAndSubmit();

    await waitFor(() => expect(registerAccountMock).toHaveBeenCalled());
    expect(registerAccountMock.mock.calls[0]?.[0]).not.toHaveProperty("utmSource");
  });
});
