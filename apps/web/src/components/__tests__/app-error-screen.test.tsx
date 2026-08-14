// @vitest-environment jsdom
/**
 * Shared root error-boundary UI (O-5, S-FIX slice C), rendered by both
 * app/error.tsx (any render error outside a nested boundary) and
 * app/global-error.tsx (a throw in the root layout itself). Before this, no
 * root-level boundary existed at all, so an error outside /dashboard fell
 * through to Next.js's stock, unbranded 500 page. Mirrors the existing
 * dashboard RouteError pattern (components/route-error.tsx): honest copy, a
 * working retry, and a way out — here "home" (the public `/`) plus a link
 * to the Privacy Policy's live contact section rather than a raw mailto
 * baked into the client bundle at build time.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppErrorScreen } from "../app-error-screen";

afterEach(() => {
  cleanup();
});

describe("AppErrorScreen (O-5, S-FIX slice C)", () => {
  it("renders an honest error message, a working Try again button, and links home + to support", () => {
    const reset = vi.fn();
    render(<AppErrorScreen error={new Error("boom")} reset={reset} />);

    expect(screen.getByText(/something went wrong/i)).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledTimes(1);

    const homeLink = screen.getByRole("link", { name: /go home/i });
    expect(homeLink.getAttribute("href")).toBe("/");

    const supportLink = screen.getByRole("link", { name: /contact support/i });
    expect(supportLink.getAttribute("href")).toBe("/privacy-policy");
  });

  it("surfaces the error digest when present, for support correlation", () => {
    const error = Object.assign(new Error("boom"), { digest: "abc123" });
    render(<AppErrorScreen error={error} reset={vi.fn()} />);
    expect(screen.getByText(/abc123/)).not.toBeNull();
  });
});
