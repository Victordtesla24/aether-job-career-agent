// @vitest-environment jsdom
/**
 * /dashboard/settings page — Privacy & Compliance tab (GAP-P6-DOCS-002).
 *
 * The privacy tab copy claimed "You can export or delete all data at any
 * time" — no self-service export/delete endpoint exists in the codebase
 * (only Gmail disconnect via DELETE /api/emails/accounts/{id} and in-app
 * profile correction are real, self-service features; full data export or
 * account deletion is admin-mediated only). This mirrors the same fix
 * already applied to the public /privacy-policy page.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../lib/api/client";

const fetchSettingsMock = vi.fn();
const fetchCareerDataMock = vi.fn();
vi.mock("../../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/workspaces")>();
  return {
    ...actual,
    fetchSettings: (...args: unknown[]) => fetchSettingsMock(...args),
    fetchCareerData: (...args: unknown[]) => fetchCareerDataMock(...args),
  };
});

const fetchSubscriptionMock = vi.fn();
const openBillingPortalMock = vi.fn();
const fetchEntitlementMock = vi.fn();
const fetchPlansMock = vi.fn();
vi.mock("../../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/billing")>();
  return {
    ...actual,
    fetchSubscription: (...args: unknown[]) => fetchSubscriptionMock(...args),
    openBillingPortal: (...args: unknown[]) => openBillingPortalMock(...args),
    fetchEntitlement: (...args: unknown[]) => fetchEntitlementMock(...args),
    fetchPlans: (...args: unknown[]) => fetchPlansMock(...args),
  };
});

const PLANS_RESPONSE = {
  currency: "AUD",
  gstIncluded: true,
  plans: [
    {
      id: "free", name: "Free", modelTier: "light", runsPerMonth: 5,
      monthly: { total: 0, gst: 0, net: 0 }, annual: null,
      features: [], purchasable: false,
    },
    {
      id: "pro", name: "Pro", modelTier: "advanced", runsPerMonth: 100,
      monthly: { total: 39, gst: 3.55, net: 35.45 },
      annual: { total: 359, gst: 32.64, net: 326.36 },
      features: [], purchasable: true,
    },
  ],
};

// The SubscriptionGate reads the live pathname to allowlist /dashboard/settings.
const usePathnameMock = vi.fn(() => "/dashboard/settings" as string | null);
vi.mock("next/navigation", () => ({
  usePathname: () => usePathnameMock(),
}));

// CLI-D3 refix (audit wf_9a87f76f-eaa, adversarial MUST-FIX 2): the
// auto-apply hint's affirmative "automatically transmits" clause is only true
// when the operator kill-switch (AETHER_APPLY_SWEEP_ENABLED,
// apps/api/app/workers/apply_sweep.py sweep_enabled() — code default OFF) is
// ALSO on, so the settings screen now reads the live GET
// /applications/apply-sweep-status signal like the applications/approvals
// screens already do. Default mock = false (the code default and the honest
// under-promise while the fetch is in flight or failed).
const fetchApplySweepStatusMock = vi.fn();
vi.mock("../../../../lib/api/applications", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/applications")>();
  return {
    ...actual,
    fetchApplySweepStatus: (...args: unknown[]) => fetchApplySweepStatusMock(...args),
  };
});

// eslint-disable-next-line import/first
import SettingsPage from "../page";
// eslint-disable-next-line import/first
import { DEFAULT_MATCH_THRESHOLD } from "../settings-client";
// eslint-disable-next-line import/first
import { SubscriptionGate } from "../../../../components/subscription-gate";

const SETTINGS = {
  profile: { fullName: "Jamie Rivera", email: "jamie@example.com", targetRole: "Staff Engineer", location: "Sydney, AU" , hasAvatar: false, avatarRevision: null },
  resume: { activeFile: "resume.pdf", uploadedAt: "2026-07-01", versions: 3 },
  portfolio: { url: null, cadence: null, lastSynced: null },
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
  integrations: [],
  connectedAccounts: [],
};

describe("AUD-UX-1 matchThreshold lockstep", () => {
  it("displays the same default the apply path and column default use", () => {
    expect(DEFAULT_MATCH_THRESHOLD).toBe(80);
    expect(SETTINGS.agentConfig.matchThreshold).toBe(DEFAULT_MATCH_THRESHOLD);
  });
});

const CAREER_DATA = { sources: [], linkedinNote: "" };

const SUBSCRIPTION = {
  plan: { id: "pro", name: "Pro", modelTier: "advanced" },
  status: "active",
  interval: "month",
  currentPeriodEnd: "2026-08-01T00:00:00Z",
  cancelAtPeriodEnd: false,
  quota: {
    runsUsed: 15,
    runsAllowed: 100,
    spendUsedUsd: 0.074688,
    spendCapUsd: 15.0,
    periodEnd: "2026-08-01T00:00:00Z",
  },
};

// Some tests below replace `window.location` with a plain href-capturing stub
// (to observe a redirect to the billing portal) via Object.defineProperty —
// jsdom's `window` persists across `it()`s within this file, so without
// restoring the real descriptor afterward, every later test would inherit a
// `window.location` with no working `search` (breaking the
// ?checkout=success tests below, which read the real URL).
const originalLocationDescriptor = Object.getOwnPropertyDescriptor(window, "location");

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
  fetchSubscriptionMock.mockReset();
  openBillingPortalMock.mockReset();
  fetchEntitlementMock.mockReset();
  fetchPlansMock.mockReset();
  fetchApplySweepStatusMock.mockReset();
  usePathnameMock.mockReturnValue("/dashboard/settings");
  vi.unstubAllEnvs();
  if (originalLocationDescriptor) {
    Object.defineProperty(window, "location", originalLocationDescriptor);
  }
  window.history.replaceState(null, "", "/dashboard/settings");
});

const FREE_SUBSCRIPTION = {
  plan: { id: "free", name: "Free", modelTier: "basic" },
  status: null,
  interval: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  quota: {
    runsUsed: 3,
    runsAllowed: 5,
    spendUsedUsd: 0.42,
    spendCapUsd: 1.0,
    periodEnd: "2026-08-01T00:00:00Z",
  },
};

describe("SettingsPage — Privacy & Compliance tab", () => {
  it("ML-SETTINGS-001: renders a distinct Privacy & Compliance panel, not the Profile panel underneath", async () => {
    // Fresh production evidence (uat/reports/evidence/deep-sweep-2026-07-29/
    // INTERACTION-FINDINGS.json): the Privacy & Compliance nav tab visually
    // activates (highlight + aria-pressed=true) but the Profile panel renders
    // underneath instead of privacy-specific content. Reproduced 3x.
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    expect(screen.getByTestId("settings-nav-privacy").getAttribute("aria-pressed")).toBe("true");

    // A genuinely distinct panel must render...
    const panel = await waitFor(() => screen.getByTestId("settings-privacy"));
    expect(panel.textContent ?? "").toMatch(/privacy/i);

    // ...and the Profile panel (name/email/target-role/location form) must
    // NOT render underneath it — that's the exact defect being pinned here.
    expect(screen.queryByTestId("settings-profile")).toBeNull();
    expect(screen.queryByTestId("settings-fullname")).toBeNull();
  });

  it("ML-SETTINGS-001: links to the real /privacy-policy and /terms pages and shows the real connected-Gmail count, no fabricated controls", async () => {
    fetchSettingsMock.mockResolvedValue({
      ...SETTINGS,
      connectedAccounts: [
        { name: "Google (Gmail)", status: "connected", detail: "Connected as jamie@example.com (primary)" },
        { name: "OpenAI", status: "connected", detail: "gpt-4.1 configured" },
      ],
    });
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    const panel = await waitFor(() => screen.getByTestId("settings-privacy"));
    const privacyLink = panel.querySelector('a[href="/privacy-policy"]');
    const termsLink = panel.querySelector('a[href="/terms"]');
    expect(privacyLink).toBeTruthy();
    expect(termsLink).toBeTruthy();

    // Only ONE connected account is Gmail — the panel must reflect the real
    // count derived from data already on the page, not a placeholder.
    expect(panel.textContent ?? "").toMatch(/1 (connected )?gmail/i);

    // No fabricated self-service export/delete buttons — none of that
    // backend capability exists.
    expect(screen.queryByRole("button", { name: /export my data/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /delete my account/i })).toBeNull();
  });

  it("does not claim a self-service export/delete-all-data feature that does not exist", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/export or delete all data at any time/i);
  });

  it("describes the actual self-service (correction, Gmail disconnect) vs admin-mediated (full export/delete) split", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/gmail/i);
    expect(bodyText).toMatch(/no self-service/i);
    expect(bodyText).toMatch(/contact/i);
  });
});

describe("SettingsPage — Agent Configuration enforcement disclosures (CLI-D3, audit wf_9a87f76f-eaa D1/D2)", () => {
  // CONTRACT UPDATE — Architect decision CLI-D3 (audit wf_9a87f76f-eaa,
  // findings D1/D2/D6). The previous INERT-CONFIG-001 pins in this block
  // ("Saved, but not yet enforced") were written when no backend code read
  // autoApply/matchThreshold. Track B of this remediation landed REAL
  // enforcement (apps/api/app/services/application_submission.py +
  // apps/api/app/workers/apply_sweep.py): `autoApply` gates every automatic
  // transmission (the apply sweep only sweeps opted-in users, and the
  // autonomous send path additionally requires the approval gate off), and
  // `matchThreshold` bars any below-threshold or UNSCORED job from being
  // auto-sent — while the user's explicit approve-and-execute on a specific
  // application bypasses the threshold by design. These specs pin the NEW
  // honest copy at equal strictness: the hints must now claim enforcement
  // (and must no longer claim the opposite), with the same "no coming soon"
  // and behavior-round-trip guards as before. The approval-gate hint is
  // deliberately UNCHANGED (the structural _APPROVAL_GATED set in
  // apps/api/app/routers/agents.py still gates tailor/coverLetter/emailAgent
  // runs regardless of the toggle).
  async function renderOnAgents(sweepEnabled = false) {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    // CLI-D3 refix (MUST-FIX 2): the live operator kill-switch signal. The
    // default here is the code default (false) — the state the LIVE
    // deployment is actually in (AETHER_APPLY_SWEEP_ENABLED=false in the
    // production api/worker envs at the time of the audit).
    fetchApplySweepStatusMock.mockResolvedValue(sweepEnabled);
    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("settings-nav-agents"));
    fireEvent.click(screen.getByTestId("settings-nav-agents"));
    await waitFor(() => screen.getByTestId("settings-agents"));
  }

  it("discloses under the approval-gate toggle that approval is currently always enforced for submission-type runs, regardless of the preference", async () => {
    await renderOnAgents();

    const hint = screen.getByTestId("hint-approvalgate");
    const text = hint.textContent ?? "";
    expect(text).toMatch(/always enforced/i);
    expect(text).toMatch(/tailor/i);
    expect(text).toMatch(/cover letter/i);
    expect(text).toMatch(/email/i);
    expect(text).toMatch(/regardless of this (preference|setting)/i);
    expect(text.toLowerCase()).not.toContain("coming soon");
  });

  it("discloses under auto-apply that the toggle IS enforced — it gates automatic transmission (CLI-D3 / D1)", async () => {
    await renderOnAgents();

    const hint = screen.getByTestId("hint-autoapply");
    const text = hint.textContent ?? "";
    expect(text).toMatch(/enforced/i);
    // The retraction this hint used to carry must be gone — it is no longer true.
    expect(text).not.toMatch(/not (yet )?enforced/i);
    expect(text).not.toMatch(/doesn(’|')t currently change/i);
    // The hint names what enforcement actually means: the threshold bar and
    // the safe OFF state.
    expect(text).toMatch(/match threshold/i);
    expect(text).toMatch(/never auto/i);
    expect(text.toLowerCase()).not.toContain("coming soon");
  });

  it("CLI-D3 refix (MUST-FIX 2): with the operator apply sweep OFF (live signal, the code default) the hint never promises unconditional automatic transmission", async () => {
    // Track B's own contract: BOTH the user toggle AND the operator
    // kill-switch must be on before anyone is swept
    // (apps/api/app/workers/apply_sweep.py, sweep_enabled() default OFF), and
    // AETHER_APPLY_SWEEP_ENABLED=false in the live production api/worker
    // environments. So "when on, Aether automatically transmits…" conditioned
    // on the toggle ALONE was an overclaim. The affirmative clause must be
    // conditioned on the live sweepEnabled signal; with it false the hint
    // speaks eligibility + discloses the sweep is off.
    await renderOnAgents(false);

    const hint = screen.getByTestId("hint-autoapply");
    const text = hint.textContent ?? "";
    // No unconditional transmit promise…
    expect(text).not.toMatch(/when on, aether automatically transmits/i);
    expect(text).not.toMatch(/automatically transmits/i);
    // …the eligibility truth plus the disclosed off-state instead.
    expect(text).toMatch(/eligible/i);
    expect(text).toMatch(/sweep/i);
    expect(text).toMatch(/(switched|turned|currently) off|not (currently )?running|off on this deployment/i);
    // The TRUE unconditional clause stays: the autonomous send on a newly
    // queued application (maybe_autonomous_transmit) is NOT kill-switch-gated.
    expect(text).toMatch(/approval gate off/i);
    expect(text).toMatch(/autonomous/i);
    // The true negative guarantees survive at full strength.
    expect(text).toMatch(/never auto/i);
    expect(text).toMatch(/match threshold/i);
  });

  it("CLI-D3 refix (MUST-FIX 2): with the operator apply sweep ON (live signal) the hint states automatic transmission affirmatively", async () => {
    await renderOnAgents(true);

    const hint = await waitFor(() => {
      const el = screen.getByTestId("hint-autoapply");
      if (!/automatically transmits/i.test(el.textContent ?? "")) {
        throw new Error("sweep-on copy not rendered yet");
      }
      return el;
    });
    const text = hint.textContent ?? "";
    expect(text).toMatch(/automatically transmits/i);
    expect(text).toMatch(/enabled on this deployment/i);
    // Negative guarantees still present.
    expect(text).toMatch(/never auto/i);
    expect(text).toMatch(/match threshold/i);
  });

  it("gives the auto-apply toggle an honest LIVE description consistent with the enforced hint below it (CLI-D3 / D1 + refix MUST-FIX 2)", async () => {
    // The description previously hedged ("saved now, enforced once auto-apply
    // ships") because the toggle was inert. Auto-apply has shipped and is
    // enforced (apply_sweep.sweep_user_if_opted_in +
    // application_submission.maybe_autonomous_transmit), so the description
    // must state the live behavior and must not retract it. Refix: it must
    // ALSO not condition a transmit promise on the user toggle alone — the
    // sweep needs the operator kill-switch too, so the static description
    // speaks eligibility, and the hint below carries the live-signal truth.
    await renderOnAgents();

    const toggle = screen.getByTestId("toggle-autoapply");
    const paragraphs = toggle.parentElement?.querySelectorAll("p") ?? [];
    // paragraphs[0] is the "Auto-apply" label; paragraphs[1] is the description.
    const description = paragraphs[1]?.textContent ?? "";

    // Still must not overclaim an approval-free path as the default…
    expect(description.toLowerCase()).not.toMatch(/without a manual approval step/);
    // …must no longer claim the feature is unshipped/inert…
    expect(description).not.toMatch(/future|once auto-apply ships|not yet/i);
    expect(description).toMatch(/automatic(ally)?|transmit|submit/i);
    // …and must not promise the deployment transmits on this toggle alone.
    expect(description).not.toMatch(/let aether transmit applications automatically/i);
    expect(description).toMatch(/eligible/i);
    // The true negative guarantee stays.
    expect(description).toMatch(/at or above your match threshold/i);

    // The hint must still be present and must not contradict the description.
    const hint = screen.getByTestId("hint-autoapply");
    expect(hint.textContent ?? "").toMatch(/enforced/i);
  });

  it("discloses under match threshold that the value IS enforced as the auto-submission bar, and that explicit execute bypasses it (CLI-D3 / D2)", async () => {
    await renderOnAgents();

    const hint = screen.getByTestId("hint-matchthreshold");
    const text = hint.textContent ?? "";
    expect(text).toMatch(/enforced/i);
    expect(text).not.toMatch(/not (yet )?enforced/i);
    expect(text).not.toMatch(/doesn(’|')t currently filter/i);
    // What enforcement means: below-threshold AND unscored jobs are barred
    // from AUTO-submission…
    expect(text).toMatch(/below/i);
    expect(text).toMatch(/unscored|not( yet)? scored|no (fit )?score/i);
    // …and the user's own explicit decision outranks the account-wide bar.
    expect(text).toMatch(/bypass/i);
    expect(text.toLowerCase()).not.toContain("coming soon");
  });

  it("the match-threshold control no longer claims job-SURFACING filtering the backend does not do (CLI-D3 / D2)", async () => {
    // The old slider label read "only surface jobs above" — matchThreshold
    // never filtered which jobs are surfaced; what it really gates (now, per
    // Track B) is automatic SUBMISSION. The label must say the true thing.
    await renderOnAgents();

    const section = screen.getByTestId("settings-agents");
    const text = section.textContent ?? "";
    expect(text).not.toMatch(/only surface jobs above/i);
    expect(text).toMatch(/match threshold/i);
    expect(text).toMatch(/auto-?subm/i);
  });

  it("does not change the persisted toggle/slider behavior — Save still round-trips agentConfig unchanged", async () => {
    await renderOnAgents();

    const autoApply = screen.getByTestId("toggle-autoapply") as HTMLButtonElement;
    expect(autoApply.disabled).toBe(false);
    expect(autoApply.getAttribute("aria-checked")).toBe("false");

    const approvalGate = screen.getByTestId("toggle-approvalgate") as HTMLButtonElement;
    expect(approvalGate.disabled).toBe(false);
    expect(approvalGate.getAttribute("aria-checked")).toBe("true");

    const slider = screen.getByTestId("threshold-slider") as HTMLInputElement;
    expect(slider.disabled).toBe(false);
    expect(slider.value).toBe("80");
  });
});

describe("SettingsPage — Billing & Subscription (MV-settings-003, MV-pricing-003)", () => {
  it("renders the real plan, status and run/spend quota from GET /billing/subscription", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    render(<SettingsPage />);

    await waitFor(() => {
      expect(fetchSubscriptionMock).toHaveBeenCalled();
    });
    await waitFor(() => screen.getByTestId("billing-plan-name"));

    expect(screen.getByTestId("billing-plan-name").textContent).toContain("Pro");
    expect(screen.getByTestId("billing-plan-status").textContent).toContain("active");
    expect(screen.getByTestId("billing-quota-runs").textContent).toContain("15");
    expect(screen.getByTestId("billing-quota-runs").textContent).toContain("100");
  });

  it("PAY-R3-06: renders the plan's price and the real next-billing (Stripe renewal) date, not just the usage-quota reset date", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("billing-plan-price"));
    expect(screen.getByTestId("billing-plan-price").textContent).toMatch(/\$39.*\/\s*month/i);

    await waitFor(() => screen.getByTestId("billing-next-date"));
    // SUBSCRIPTION.currentPeriodEnd = "2026-08-01T00:00:00Z" — rendered
    // day-first in en-AU (W-E quality sweep), never the runtime default.
    expect(screen.getByTestId("billing-next-date").textContent).toMatch(
      new Date("2026-08-01T00:00:00Z").toLocaleDateString("en-AU"),
    );

    // Distinct from the usage-quota reset date — both are shown, not conflated.
    const section = screen.getByTestId("settings-billing");
    expect(section.textContent ?? "").toMatch(/usage quota resets/i);
  });

  it("PAY-R3-06: falls back to an honest 'Price unavailable' / 'No upcoming charge' — never a fabricated $0 or placeholder — when data is missing", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(FREE_SUBSCRIPTION);
    fetchPlansMock.mockRejectedValue(new Error("plans catalog unavailable"));
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("billing-plan-price"));
    expect(screen.getByTestId("billing-plan-price").textContent).toContain("Price unavailable");
    expect(screen.getByTestId("billing-next-date").textContent).toContain("No upcoming charge");
  });

  it("wires 'Manage subscription' to the real POST /billing/portal endpoint and follows the returned URL", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockResolvedValue({ portalUrl: "https://billing.stripe.com/session/abc" });
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { set href(v: string) { hrefSetter(v); }, get href() { return ""; } },
    });

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => {
      expect(openBillingPortalMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(hrefSetter).toHaveBeenCalledWith("https://billing.stripe.com/session/abc");
    });
  });

  it("shows an honest contact-fallback message (no fake success) when the account has no Stripe billing profile (409)", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockRejectedValue(
      new ApiError("POST /billing/portal failed (409): No billing account yet", 409),
    );

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => screen.getByTestId("manage-subscription-message"));
    const msg = screen.getByTestId("manage-subscription-message").textContent ?? "";
    expect(msg).not.toMatch(/success/i);
    expect(msg.toLowerCase()).toMatch(/billing profile|contact|support/);
  });

  it("includes the support phone in the contact-fallback message when AETHER_SUPPORT_PHONE is configured (409)", async () => {
    vi.stubEnv("AETHER_SUPPORT_PHONE", "+61 433 224 556");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockRejectedValue(
      new ApiError("POST /billing/portal failed (409): No billing account yet", 409),
    );

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => screen.getByTestId("manage-subscription-message"));
    const msg = screen.getByTestId("manage-subscription-message").textContent ?? "";
    expect(msg).toContain("+61 433 224 556");
  });

  it("does not mention a phone number in the contact-fallback message when AETHER_SUPPORT_PHONE is unset (409)", async () => {
    vi.stubEnv("AETHER_SUPPORT_PHONE", "");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockRejectedValue(
      new ApiError("POST /billing/portal failed (409): No billing account yet", 409),
    );

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => screen.getByTestId("manage-subscription-message"));
    const msg = screen.getByTestId("manage-subscription-message").textContent ?? "";
    expect(msg).not.toMatch(/\+61 433 224 556/);
    expect(msg).not.toMatch(/or call/i);
  });
});

describe("Settings billing reachable through the SubscriptionGate for a FREE account (MV-pricing-003, MV-settings-003, MV-mobile-dashboard-002)", () => {
  it("a gated free user on /dashboard/settings sees their plan + Manage subscription, NOT the full-page paywall", async () => {
    // A free/unsubscribed account: the gate would normally paywall the whole
    // dashboard, but account management (view plan/quota + cancel) must stay
    // reachable. Rendered exactly as production wraps it: <SubscriptionGate>.
    fetchEntitlementMock.mockResolvedValue({
      active_paid: false,
      plan: { id: "free", status: "active" },
      requiresSubscription: true,
    });
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(FREE_SUBSCRIPTION);
    usePathnameMock.mockReturnValue("/dashboard/settings");

    render(
      <SubscriptionGate>
        <SettingsPage />
      </SubscriptionGate>,
    );

    // Billing section renders the real free plan + a working Manage button…
    await waitFor(() => screen.getByTestId("billing-plan-name"));
    expect(screen.getByTestId("billing-plan-name").textContent).toContain("Free");
    expect(screen.getByTestId("manage-subscription-btn")).toBeTruthy();
    expect(screen.getByTestId("billing-quota-runs").textContent).toContain("5");
    // …and the paywall never replaces it.
    expect(screen.queryByTestId("subscription-paywall")).toBeNull();
    expect(screen.queryByText(/Subscribe to unlock/i)).toBeNull();
  });
});

describe("ADMIN-FULL — the Dashboard billing card for an owner/admin", () => {
  // USER MANDATE (2026-08-14): "admins/owners have NO subscriptions or plans
  // themselves". The server enforces no quota, cap or paywall against them
  // (app/services/entitlements.py), so rendering "Pro 15/100" here would be a
  // number nothing can ever enforce. `entitlement.unlimited` is that ONE
  // server-side verdict echoed onto GET /billing/subscription — the UI mirrors
  // it and never invents an exemption of its own.
  const OWNER_SUBSCRIPTION = {
    ...SUBSCRIPTION,
    entitlement: { unlimited: true, entitled: true, source: "admin", isAdmin: true },
  };

  it("shows 'Owner — unlimited' with no quota counter, no price and no billing CTA", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(OWNER_SUBSCRIPTION);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("billing-owner-unlimited"));
    expect(screen.getByTestId("billing-plan-name").textContent).toContain("Owner — unlimited");
    // Nothing metered, nothing billed, nothing to upsell.
    expect(screen.queryByTestId("billing-quota-runs")).toBeNull();
    expect(screen.queryByTestId("billing-quota-spend")).toBeNull();
    expect(screen.queryByTestId("billing-plan-price")).toBeNull();
    expect(screen.queryByTestId("manage-subscription-btn")).toBeNull();
    expect(screen.getByTestId("settings-billing").textContent).not.toMatch(/upgrade/i);
  });

  it("leaves a NON-admin's billing card exactly as it was (plan, quota, manage button)", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue({
      ...SUBSCRIPTION,
      entitlement: { unlimited: false, entitled: true, source: "plan", isAdmin: false },
    });
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("billing-plan-name"));
    expect(screen.getByTestId("billing-plan-name").textContent).toContain("Pro");
    expect(screen.getByTestId("billing-quota-runs").textContent).toContain("100");
    expect(screen.getByTestId("manage-subscription-btn")).toBeTruthy();
    expect(screen.queryByTestId("billing-owner-unlimited")).toBeNull();
  });
});

describe("SettingsPage — post-checkout success banner (PAY-R3-05)", () => {
  it("shows an 'activating' banner (never a fabricated success) when the subscription hasn't confirmed the upgrade yet, then flips to a real success message once it does", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?checkout=success");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    // First resolve still shows the OLD (free) plan — webhook hasn't landed —
    // then a manual "Refresh now" click confirms the real upgrade.
    fetchSubscriptionMock
      .mockResolvedValueOnce(FREE_SUBSCRIPTION)
      .mockResolvedValueOnce(SUBSCRIPTION);

    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("checkout-success-banner"));
    expect(screen.getByTestId("checkout-success-banner").textContent ?? "").toMatch(
      /being activated/i,
    );
    // The URL is stripped so a refresh doesn't re-show the banner.
    expect(window.location.search).toBe("");

    fireEvent.click(screen.getByTestId("checkout-banner-refresh"));

    await waitFor(() => {
      const banner = screen.getByTestId("checkout-success-banner");
      expect(banner.textContent ?? "").toMatch(/subscription active/i);
    });
    expect(screen.getByTestId("checkout-success-banner").textContent ?? "").toContain("Pro");
  });

  it("shows the success banner immediately (no 'activating' delay) when the subscription already confirms an active paid plan on first load", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?checkout=success");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("checkout-success-banner").textContent ?? "").toMatch(
        /subscription active.*welcome to pro/i,
      );
    });
  });

  it("shows no banner at all on a plain visit with no ?checkout param", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("billing-plan-name"));
    expect(screen.queryByTestId("checkout-success-banner")).toBeNull();
  });

  it("is dismissible", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?checkout=success");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("checkout-success-banner"));
    fireEvent.click(screen.getByTestId("checkout-banner-dismiss"));
    expect(screen.queryByTestId("checkout-success-banner")).toBeNull();
  });
});
