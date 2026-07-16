// @vitest-environment jsdom
/**
 * /terms page (GAP-P6-DOCS-002).
 *
 * The live page previously said users can "delete your account at any time
 * via the Settings page" (no such self-service endpoint exists) and never
 * mentioned the subscription product at all — no tiers, no pricing, no GST,
 * no quota model, no cancellation process. This page went live in production
 * still describing a free tool with Delaware governing law and zero mention
 * of money changing hands. These assertions pin the honest, ratified
 * subscription terms down so the gap cannot silently regress.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import TermsPage from "../page";

afterEach(() => {
  cleanup();
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

  it("leaves operator-specific legal identity and refund policy as explicit placeholders", () => {
    render(<TermsPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toContain("[Business Name]");
    expect(bodyText).toContain("[Operator ABN]");
    expect(bodyText).toMatch(/\[Operator: state your refund policy/);
  });
});
