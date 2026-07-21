// @vitest-environment jsdom
/**
 * /privacy-policy page (GAP-P6-DOCS-002; MV-privacy-policy-002/003).
 *
 * The live page previously claimed users can "Delete your data via the
 * Settings page" — no such self-service delete/export endpoint exists in the
 * codebase (only an admin-mediated path). This page also predated the
 * subscription build and never mentioned Stripe (payments), the configured
 * LLM provider, or the encryption/rate-limiting controls that actually exist.
 * These assertions pin the honest content down so the false claim cannot
 * silently return.
 *
 * MV-privacy-policy-002/003 (manual-verification, 2026-07-17/18): the page
 * had zero reference to Australian privacy law, and its §5/§7 directed
 * users to a nonexistent "Settings page or in-app support channel" to
 * exercise data export/deletion rights. These assertions pin the Privacy
 * Act 1988 (Cth) / Australian Privacy Principles references and the honest,
 * env-sourced contact path down.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PrivacyPolicyPage from "../page";

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
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

  it("MV-privacy-policy-002: references the Privacy Act 1988 (Cth) and the Australian Privacy Principles", () => {
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/Privacy Act 1988 \(Cth\)/);
    expect(bodyText).toMatch(/Australian Privacy Principles/);
    expect(bodyText).toMatch(/Australia/);
    expect(bodyText).toMatch(/OAIC|Office of the Australian Information Commissioner/);
  });

  it("MV-privacy-policy-003: states an honest 'not yet published' contact instead of a nonexistent Settings/support channel when no support email is configured", () => {
    vi.stubEnv("AETHER_SUPPORT_EMAIL", "");
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/support contact address has not yet been published/i);
    expect(bodyText).not.toMatch(/reach us via the settings page/i);
    expect(bodyText).not.toMatch(/in-app support channel/i);
  });

  it("MV-privacy-policy-003: renders a real mailto contact once AETHER_SUPPORT_EMAIL is configured", () => {
    vi.stubEnv("AETHER_SUPPORT_EMAIL", "privacy@example-operator.com");
    render(<PrivacyPolicyPage />);
    const mailLink = screen.getByRole("link", { name: /privacy@example-operator\.com/i });
    expect(mailLink.getAttribute("href")).toBe("mailto:privacy@example-operator.com");
  });

  it("renders the operator support phone once AETHER_SUPPORT_PHONE is configured", () => {
    vi.stubEnv("AETHER_SUPPORT_EMAIL", "privacy@example-operator.com");
    vi.stubEnv("AETHER_SUPPORT_PHONE", "+61 433 224 556");
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toContain("+61 433 224 556");
    const telLink = screen.getByRole("link", { name: /\+61 433 224 556/ });
    expect(telLink.getAttribute("href")).toBe("tel:+61433224556");
  });

  it("renders no phone number at all when AETHER_SUPPORT_PHONE is unset", () => {
    vi.stubEnv("AETHER_SUPPORT_PHONE", "");
    render(<PrivacyPolicyPage />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/\+61 433 224 556/);
    expect(bodyText).not.toMatch(/or call/i);
    expect(bodyText).not.toMatch(/you can call/i);
  });
});
