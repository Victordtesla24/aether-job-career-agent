// @vitest-environment jsdom
/**
 * Root app/not-found.tsx (O-5, S-FIX slice C).
 *
 * Before this, no top-level app/not-found.tsx existed (only nested
 * dashboard/* error.tsx boundaries), so a bogus route (e.g. /foobar) fell
 * through to Next.js's stock, unbranded 404 with no path back into the app
 * or to support. This pins down a branded page that always offers a way
 * home and, honestly, either a real mailto contact (when
 * AETHER_SUPPORT_EMAIL is configured) or a link to the Privacy Policy's
 * live contact section (never a fabricated address) — mirrors the
 * env-sourced honesty convention in lib/config/legal.ts.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NotFound from "../not-found";

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("Root not-found page (O-5, S-FIX slice C)", () => {
  it("renders a branded 404 message with a link back into the app", () => {
    render(<NotFound />);
    expect(screen.getByText(/page not found/i)).not.toBeNull();
    expect(screen.getByRole("link", { name: /go home/i })).toBeTruthy();
  });

  it("renders a real mailto contact link once AETHER_SUPPORT_EMAIL is configured", () => {
    vi.stubEnv("AETHER_SUPPORT_EMAIL", "help@example-operator.com");
    render(<NotFound />);
    const link = screen.getByRole("link", { name: /contact support/i });
    expect(link.getAttribute("href")).toBe("mailto:help@example-operator.com");
  });

  it("falls back to the owner-declared brand support address when the env is unset", () => {
    // Contract change (owner directive 2026-08-16): the support address is no
    // longer unknowable when AETHER_SUPPORT_EMAIL is unset — lib/brand.ts
    // carries the owner-declared address, so the page renders a REAL mailto
    // instead of the historical privacy-policy fallback. Not a fabrication:
    // the address is owner-published brand identity, env still overrides.
    vi.stubEnv("AETHER_SUPPORT_EMAIL", "");
    render(<NotFound />);
    const link = screen.getByRole("link", { name: /^contact support$/i });
    expect(link.getAttribute("href")).toBe("mailto:sarkar.vikram@gmail.com");
  });
});
