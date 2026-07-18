// @vitest-environment jsdom
/**
 * AuthGuard — session gate for the /dashboard shell. RED first: the guard
 * currently redirects to bare /login, dropping the intended deep-link
 * destination (MV-login-002). This test pins the ?next round-trip.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: replaceMock }) }));

// eslint-disable-next-line import/first
import { AuthGuard } from "../auth-guard";

afterEach(() => {
  cleanup();
  replaceMock.mockReset();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/dashboard");
});

describe("AuthGuard", () => {
  it("renders children when a session token is present", () => {
    window.localStorage.setItem("aether_token", "jwt-123");
    render(
      <AuthGuard>
        <div>workspace</div>
      </AuthGuard>,
    );
    expect(screen.getByText("workspace")).toBeTruthy();
  });

  it("redirects an unauthenticated deep-link to /login preserving the intended path (MV-login-002)", () => {
    window.history.replaceState(null, "", "/dashboard/resume-studio?tab=ats");
    render(
      <AuthGuard>
        <div>workspace</div>
      </AuthGuard>,
    );
    expect(screen.queryByText("workspace")).toBeNull();
    expect(replaceMock).toHaveBeenCalledWith(
      "/login?next=" + encodeURIComponent("/dashboard/resume-studio?tab=ats"),
    );
  });
});
