// @vitest-environment jsdom
/**
 * /privacy-policy page (GAP-P6-DOCS-002).
 *
 * The live page previously claimed users can "Delete your data via the
 * Settings page" — no such self-service delete/export endpoint exists in the
 * codebase (only an admin-mediated path). This page also predated the
 * subscription build and never mentioned Stripe (payments), the configured
 * LLM provider, or the encryption/rate-limiting controls that actually exist.
 * These assertions pin the honest content down so the false claim cannot
 * silently return.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import PrivacyPolicyPage from "../page";

afterEach(() => {
  cleanup();
});

describe("PrivacyPolicyPage", () => {
  it("renders", () => {
    render(<PrivacyPolicyPage />);
    expect(screen.getByText("Privacy Policy")).not.toBeNull();
  });

  it("does not claim a self-service delete-your-data feature that does not exist", () => {
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/delete your data via the settings page/i);
    expect(bodyText).not.toMatch(/permanently deleted within 30 days/i);
  });

  it("describes the actual (admin-mediated) data export/deletion process instead", () => {
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/no self-service/i);
    expect(bodyText).toMatch(/contact us/i);
  });

  it("discloses Stripe as the payment processor and its current activation status", () => {
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toContain("Stripe");
    expect(bodyText).toMatch(/not yet active|is not yet/i);
  });

  it("discloses the configured LLM provider, Gmail OAuth token encryption, and Postgres storage", () => {
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/LLM provider/i);
    expect(bodyText).toContain("OAuth");
    expect(bodyText).toMatch(/encrypted/i);
    expect(bodyText).toMatch(/PostgreSQL/i);
  });

  it("discloses concrete security controls: rate limiting, Fernet encryption, no secrets in source", () => {
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/rate.?limit/i);
    expect(bodyText).toMatch(/Fernet/);
    expect(bodyText).toMatch(/bcrypt/i);
    expect(bodyText).toMatch(/no secrets/i);
  });
});
