// @vitest-environment jsdom
/**
 * AUD-META-1 (cohort residual) — the policy-tier cohort widget must never
 * describe a never-transmitted application as submitted/applied/sent.
 *
 * Ledger: *"Dashboard/Analytics label apps 'submitted/applied' when not
 * transmitted. FIX: expose a distinct transmitted count; copy 'prepared' vs
 * 'sent'."* The API half now returns `prepared` (left draft) and
 * `transmitted` (`transmittedAt IS NOT NULL`) as separate counts, with the
 * conversion rate computed over `transmitted` only. This suite pins the copy
 * that renders them: the rate's basis names VERIFIED SENDS, the prepared
 * population is called "prepared", and the word "submitted" is never applied
 * to either bucket.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PolicyCohortProgress } from "../PolicyProgress";
import type { PolicyCohorts } from "../../../lib/api/agentPolicy";

afterEach(cleanup);

const COHORTS: PolicyCohorts = {
  target: 20,
  minSampleSize: 5,
  cohorts: [
    {
      tier: "standard",
      label: "Standard rigor",
      // 24 prepared, only 6 verifiably sent — the exact shape the audit found
      // in production, where the widget called all 24 "submitted".
      prepared: 24,
      transmitted: 6,
      interviewed: 1,
      conversionRate: 16.67,
      sufficientSample: true,
      meetsTarget: false,
      gapPoints: 3.33,
    },
    {
      tier: "heightened",
      label: "Heightened rigor",
      prepared: 12,
      transmitted: 0,
      interviewed: 0,
      conversionRate: null,
      sufficientSample: false,
      meetsTarget: null,
      gapPoints: null,
    },
  ],
  untagged: { prepared: 290, transmitted: 0, interviewed: 4, reason: null },
};

describe("PolicyCohortProgress — prepared vs sent (verified)", () => {
  it("states the rate's denominator as verified sends, not as 'submitted'", () => {
    render(<PolicyCohortProgress cohorts={COHORTS} />);
    const row = screen.getByTestId("policy-cohort-standard");
    expect(row.textContent).toMatch(/6 sent \(verified\)/i);
    expect(row.textContent).toMatch(/16\.67%/);
    expect(row.textContent?.toLowerCase()).not.toContain("submitted");
  });

  it("discloses the prepared applications that were never verified as sent", () => {
    render(<PolicyCohortProgress cohorts={COHORTS} />);
    const row = screen.getByTestId("policy-cohort-standard");
    expect(row.textContent).toMatch(/24 prepared/i);
    expect(row.textContent).toMatch(/18 not verified as sent/i);
  });

  it("prints no rate for a tier with prepared applications but no verified send", () => {
    render(<PolicyCohortProgress cohorts={COHORTS} />);
    const row = screen.getByTestId("policy-cohort-heightened");
    expect(row.textContent).not.toMatch(/0%/);
    expect(row.textContent?.toLowerCase()).toMatch(/at least 5 verified sends/);
    expect(row.textContent).toMatch(/12 prepared/i);
  });

  it("says on the ribbon what it spans — prepared, with the sent subtotal", () => {
    render(<PolicyCohortProgress cohorts={COHORTS} />);
    const panel = screen.getByTestId("policy-cohorts");
    const note = within(panel).getByTestId("bullet-coverage-note");
    // 24 + 12 prepared under a tier + 290 untagged; 6 verified sends in total.
    expect(note.textContent).toContain("326");
    expect(note.textContent).toMatch(/6 of them carry a verified send/i);
    expect(note.textContent).toMatch(/preparation is not proof of sending/i);
  });

  it("never labels any part of the panel 'submitted', 'applied' or 'sent' without proof", () => {
    render(<PolicyCohortProgress cohorts={COHORTS} />);
    const panel = screen.getByTestId("policy-cohorts");
    const text = (panel.textContent ?? "").toLowerCase();
    expect(text).not.toContain("submitted");
    expect(text).not.toContain("applied");
    // "sent" only ever appears qualified as verified, or as the explicit
    // negative ("not verified as sent" / "not proof of sending").
    for (const match of text.match(/[^.·;]*\bsent\b[^.·;]*/g) ?? []) {
      expect(
        /verified|not proof of sending/.test(match),
        `unqualified "sent" claim in cohort panel: ${match.trim()}`,
      ).toBe(true);
    }
  });
});
