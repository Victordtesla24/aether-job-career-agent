// @vitest-environment jsdom
/**
 * /terms page (GAP-P6-DOCS-002; MV-terms-002/003/004).
 *
 * The live page previously said users can "delete your account at any time
 * via the Settings page" (no such self-service endpoint exists) and never
 * mentioned the subscription product at all — no tiers, no pricing, no GST,
 * no quota model, no cancellation process. This page went live in production
 * still describing a free tool with Delaware governing law and zero mention
 * of money changing hands. These assertions pin the honest, ratified
 * subscription terms down so the gap cannot silently regress.
 *
 * MV-terms-002/003/004 (manual-verification, 2026-07-17/18): production
 * still rendered live, unfilled "[Operator ABN]" / "[Business Name]" /
 * refund-policy bracket placeholders, told users to reach a nonexistent
 * "Settings page or in-app support channel", and mixed a USD liability cap +
 * Delaware/USA governing law into an otherwise AUD/GST/ABN Australian
 * document. These assertions pin the honest replacement content down: no
 * raw bracket ever renders, operator identity/contact come from env vars
 * with honest (never fabricated) defaults, and currency/jurisdiction are
 * reconciled to Australia.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TermsPage from "../page";

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("TermsPage", () => {
  it("renders", () => {
    render(<TermsPage />);
    expect(screen.getByText("Terms & Conditions")).not.toBeNull();
  });

  it("does not claim a self-service account-deletion feature that does not exist", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/delete your account at any time via the settings page/i);
  });

  it("lists all four ratified tiers with GST-inclusive AUD pricing", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    for (const price of ["A$0", "A$19", "A$179", "A$39", "A$359", "A$69", "A$649"]) {
      expect(bodyText).toContain(price);
    }
  });

  it("discloses the 10% GST breakdown formula", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/10%/);
    expect(bodyText).toMatch(/GST/);
    expect(bodyText).toMatch(/total\s*\/\s*11/);
  });

  it("describes the agent-run quota model with monthly reset and upgrade prompt on exhaustion", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/5 agent runs per month/);
    expect(bodyText).toMatch(/30 agent runs per month/);
    expect(bodyText).toMatch(/100 agent runs per month/);
    expect(bodyText).toMatch(/300 agent runs per month/);
    expect(bodyText).toMatch(/resets? (automatically )?at the start of each billing period/i);
    expect(bodyText).toMatch(/upgrade/i);
  });

  it("describes cancellation via the Stripe billing portal with access until period end", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/Stripe Billing Portal/i);
    expect(bodyText).toMatch(/end of your current billing period/i);
  });

  it("states live payment processing is pending operator Stripe setup, not already active", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/not yet active/i);
  });

  it("MV-terms-002: never renders a raw bracket placeholder anywhere on the page", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/\[Operator/i);
    expect(bodyText).not.toMatch(/\[Business Name\]/i);
    expect(bodyText).not.toContain("[");
    expect(bodyText).not.toContain("]");
  });

  it("MV-terms-002: falls back to an honest default business name and no-ABN statement when operator env vars are unset", () => {
    vi.stubEnv("AETHER_OPERATOR_BUSINESS_NAME", "");
    vi.stubEnv("AETHER_OPERATOR_ABN", "");
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/operated by\s*Aether/i);
    expect(bodyText).toMatch(/has not yet been published/i);
    expect(bodyText).not.toMatch(/\(ABN/i);
  });

  it("MV-terms-002: renders the operator-configured business name and ABN once set via env vars", () => {
    vi.stubEnv("AETHER_OPERATOR_BUSINESS_NAME", "Aether Pty Ltd");
    vi.stubEnv("AETHER_OPERATOR_ABN", "12 345 678 901");
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toContain("Aether Pty Ltd");
    expect(bodyText).toContain("12 345 678 901");
    expect(bodyText).not.toMatch(/Australian Business Number has not yet been published/i);
  });

  it("MV-terms-002: states an honest, non-fabricated refund process instead of a placeholder policy", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/handled manually.*case-by-case basis.*operator/i);
    expect(bodyText).not.toMatch(/pro-rated refunds within X days/i);
  });

  it("MV-terms-004: reconciles the liability cap and governing law to Australia (no USD/Delaware/USA)", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/fifty Australian dollars \(A\$50\)/i);
    expect(bodyText).not.toMatch(/U\.S\. dollars/i);
    expect(bodyText).toMatch(/Victoria, Australia/);
    expect(bodyText).not.toMatch(/Delaware/i);
    expect(bodyText).not.toMatch(/\bUSA\b/);
  });

  it("MV-terms-003: states an honest 'not yet published' contact instead of a nonexistent Settings/support channel when no support email is configured", () => {
    vi.stubEnv("AETHER_SUPPORT_EMAIL", "");
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/support contact address has not yet been published/i);
    expect(bodyText).not.toMatch(/reach us via the settings page/i);
    expect(bodyText).not.toMatch(/in-app support channel/i);
  });

  it("MV-terms-003: renders a real mailto contact once AETHER_SUPPORT_EMAIL is configured", () => {
    vi.stubEnv("AETHER_SUPPORT_EMAIL", "support@example-operator.com");
    render(<TermsPage />);
    const mailLink = screen.getByRole("link", { name: /support@example-operator\.com/i });
    expect(mailLink.getAttribute("href")).toBe("mailto:support@example-operator.com");
  });
});
