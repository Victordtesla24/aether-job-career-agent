/** AGT-APPS — pure board logic tests (stage mapping, fit colour, time, filter/sort). */
import { describe, expect, it } from "vitest";

import type { Job } from "../../../lib/api/jobs";
import type { TrackerApplication } from "../tracker-api";
import {
  APP_STAGE,
  APP_STAGE_KEYS,
  JOB_STAGE_KEYS,
  STAGE_DEFS,
  STAGE_TO_APP_STATUS,
  STAGE_TO_JOB_STATUS,
  automaticSubmissionDisclaimer,
  buildStages,
  cardMatchesFilter,
  channelLabel,
  describeTransmission,
  fitClass,
  initials,
  manualStepLabel,
  manualStepTooltip,
  moveTargetsFor,
  notTransmittedReason,
  shortDate,
  sortCards,
  timeAgo,
  viewStages,
  type StageCard,
  type StageKey,
} from "../tracker-lib";

const NOW = new Date("2026-07-10T12:00:00Z").getTime();

function app(over: Partial<TrackerApplication>): TrackerApplication {
  return {
    id: "a1",
    jobId: "j1",
    resumeId: "r1",
    status: "draft",
    jobTitle: "Engineer",
    company: "Acme",
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
    ...over,
  } as TrackerApplication;
}

function job(over: Partial<Job>): Job {
  return {
    id: "j1",
    title: "Engineer",
    company: "Acme",
    status: "discovered",
    remote: false,
    saved: false,
    ...over,
  } as Job;
}

describe("STAGE_DEFS", () => {
  it("has the 8 wireframe stages in order with wireframe labels", () => {
    expect(STAGE_DEFS.map((s) => s.label)).toEqual([
      "Discovered",
      "Evaluating",
      "Tailoring",
      "Ready to Apply",
      "Submitted",
      "In Review",
      "Interview",
      "Offer",
    ]);
  });
});

describe("buildStages", () => {
  it("maps application statuses to the last five stages", () => {
    const stages = buildStages(
      [
        app({ id: "a1", status: "draft" }),
        app({ id: "a2", jobId: "j2", status: "submitted" }),
        app({ id: "a3", jobId: "j3", status: "screening" }),
        app({ id: "a4", jobId: "j4", status: "interview" }),
        app({ id: "a5", jobId: "j5", status: "offer" }),
        app({ id: "a6", jobId: "j6", status: "rejected" }),
      ],
      [],
    );
    const byKey = Object.fromEntries(stages.map((s) => [s.key, s.cards.map((c) => c.id)]));
    expect(byKey["ready"]).toEqual(["a1"]);
    expect(byKey["submitted"]).toEqual(["a2"]);
    expect(byKey["in-review"]).toEqual(["a3"]);
    expect(byKey["interview"]).toEqual(["a4"]);
    expect(byKey["offer"]).toEqual(["a5"]);
    // rejected never lands on the board
    expect(stages.flatMap((s) => s.cards.map((c) => c.id))).not.toContain("a6");
  });

  it("maps pipeline jobs to the first three stages, excluding applied-to jobs", () => {
    const stages = buildStages(
      [app({ id: "a1", jobId: "j-applied", status: "submitted" })],
      [
        job({ id: "j-d", status: "discovered" }),
        job({ id: "j-s", status: "screening" }),
        job({ id: "j-m", status: "matched" }),
        job({ id: "j-t", status: "tailoring" }),
        job({ id: "j-applied", status: "applied" }),
      ],
    );
    const byKey = Object.fromEntries(stages.map((s) => [s.key, s.cards.map((c) => c.id)]));
    expect(byKey["discovered"]).toEqual(["job-j-d"]);
    expect(byKey["evaluating"]).toEqual(["job-j-s", "job-j-m"]);
    expect(byKey["tailoring"]).toEqual(["job-j-t"]);
    // the applied job is represented by its application card, not a job card
    expect(stages.flatMap((s) => s.cards.map((c) => c.id))).not.toContain("job-j-applied");
  });

  it("prefers the application's own fitScore, falling back to the job's", () => {
    const stages = buildStages(
      [
        app({ id: "a1", jobId: "jx", status: "offer", fitScore: 95.4 }),
        app({ id: "a2", jobId: "j-f", status: "interview" }),
      ],
      [job({ id: "j-f", status: "applied", fitScore: 88.2 })],
    );
    const offer = stages.find((s) => s.key === "offer")!.cards[0];
    const interview = stages.find((s) => s.key === "interview")!.cards[0];
    expect(offer.fit).toBe(95);
    expect(interview.fit).toBe(88);
  });

  it("exposes answers as tracker metadata", () => {
    const stages = buildStages(
      [app({ id: "a1", status: "offer", answers: { offerAmount: "$225k", offerDeadline: "2026-07-18" } })],
      [],
    );
    expect(stages.find((s) => s.key === "offer")!.cards[0].meta.offerAmount).toBe("$225k");
  });

  // GAP-P4-050 regression guard: the board must always mount all 8 wireframe
  // columns (Discovered..Offer) — a stage with zero cards is still a column,
  // never silently dropped/unmounted client-side.
  it("always returns all 8 wireframe columns, in order, even with no data", () => {
    const stages = buildStages([], []);
    expect(stages).toHaveLength(8);
    expect(stages.map((s) => s.key)).toEqual(STAGE_DEFS.map((d) => d.key));
    for (const s of stages) expect(s.cards).toEqual([]);
  });

  it("keeps every column mounted with a real card in it (draft..offer all populate a distinct stage)", () => {
    const stages = buildStages(
      [
        app({ id: "a1", jobId: "j1", status: "draft" }),
        app({ id: "a2", jobId: "j2", status: "submitted" }),
        app({ id: "a3", jobId: "j3", status: "screening" }),
        app({ id: "a4", jobId: "j4", status: "interview" }),
        app({ id: "a5", jobId: "j5", status: "offer" }),
      ],
      [
        job({ id: "j6", status: "discovered" }),
        job({ id: "j7", status: "screening" }),
        job({ id: "j8", status: "tailoring" }),
      ],
    );
    expect(stages).toHaveLength(8);
    for (const s of stages) expect(s.cards.length).toBeGreaterThan(0);
  });
});

describe("FEAT-B2 stage-move helpers", () => {
  it("STAGE_TO_APP_STATUS is the exact inverse of APP_STAGE over the 5 app-fed stages", () => {
    for (const [status, stage] of Object.entries(APP_STAGE)) {
      expect(STAGE_TO_APP_STATUS[stage as StageKey]).toBe(status);
    }
    expect(Object.keys(STAGE_TO_APP_STATUS).sort()).toEqual([...APP_STAGE_KEYS].sort());
  });

  it("STAGE_TO_JOB_STATUS covers the 3 job-fed stages, evaluating → screening", () => {
    expect(Object.keys(STAGE_TO_JOB_STATUS).sort()).toEqual([...JOB_STAGE_KEYS].sort());
    expect(STAGE_TO_JOB_STATUS.discovered).toBe("discovered");
    expect(STAGE_TO_JOB_STATUS.evaluating).toBe("screening");
    expect(STAGE_TO_JOB_STATUS.tailoring).toBe("tailoring");
  });

  it("moveTargetsFor: application cards offer the other 4 app-fed stages only", () => {
    const card: StageCard = {
      id: "a1",
      title: "Engineer",
      company: "Acme",
      updatedAt: "2026-07-01T00:00:00Z",
      app: app({ status: "submitted" }),
      meta: {},
    };
    const targets = moveTargetsFor(card, "submitted");
    expect(targets).toEqual(["ready", "in-review", "interview", "offer"]);
    expect(targets).not.toContain("submitted");
    for (const t of targets) expect(JOB_STAGE_KEYS).not.toContain(t);
  });

  it("moveTargetsFor: pipeline job cards offer the other 2 job-fed stages only", () => {
    const card: StageCard = {
      id: "job-j1",
      title: "Engineer",
      company: "Acme",
      updatedAt: "2026-07-01T00:00:00Z",
      meta: {},
    };
    const targets = moveTargetsFor(card, "evaluating");
    expect(targets).toEqual(["discovered", "tailoring"]);
    for (const t of targets) expect(APP_STAGE_KEYS).not.toContain(t);
  });

  it("moveTargetsFor allows backward application moves (offer → ready listed)", () => {
    const card: StageCard = {
      id: "a2",
      title: "Engineer",
      company: "Acme",
      updatedAt: "2026-07-01T00:00:00Z",
      app: app({ status: "offer" }),
      meta: {},
    };
    expect(moveTargetsFor(card, "offer")).toContain("ready");
  });
});

describe("fitClass / initials / time formatting", () => {
  it("colours ≥85 green and <85 amber (wireframe 94 green / 81 amber)", () => {
    expect(fitClass(94)).toContain("green");
    expect(fitClass(85)).toContain("green");
    expect(fitClass(84)).toContain("yellow");
    expect(fitClass(81)).toContain("yellow");
  });

  it("builds initials from up to two words", () => {
    expect(initials("Canva")).toBe("C");
    expect(initials("Queensland Government")).toBe("QG");
    expect(initials("")).toBe("?");
  });

  it("formats relative time like the wireframe", () => {
    expect(timeAgo(new Date(NOW - 2 * 60_000).toISOString(), NOW)).toBe("2 min ago");
    expect(timeAgo(new Date(NOW - 30_000).toISOString(), NOW)).toBe("just now");
    expect(timeAgo(new Date(NOW - 3 * 3_600_000).toISOString(), NOW)).toBe("3 h ago");
    expect(timeAgo(new Date(NOW - 4 * 86_400_000).toISOString(), NOW)).toBe("4 d ago");
    expect(timeAgo("garbage", NOW)).toBe("—");
  });

  it("formats short badge dates", () => {
    expect(shortDate("2026-07-03")).toBe("3 July");
  });
});

describe("filter / sort", () => {
  const cards: StageCard[] = [
    { id: "c1", title: "A", company: "Zeta", updatedAt: "2026-07-09T00:00:00Z", fit: 92, meta: {} },
    { id: "c2", title: "B", company: "Alpha", updatedAt: "2026-07-10T00:00:00Z", fit: 78, meta: {} },
    {
      id: "c3",
      title: "C",
      company: "Mid",
      updatedAt: "2026-07-08T00:00:00Z",
      fit: 87,
      app: app({ id: "c3", status: "draft" }),
      meta: {},
    },
  ];

  it("filters by fit threshold and needs-approval", () => {
    expect(cards.filter((c) => cardMatchesFilter(c, "high-fit")).map((c) => c.id)).toEqual([
      "c1",
      "c3",
    ]);
    expect(cards.filter((c) => cardMatchesFilter(c, "below-fit")).map((c) => c.id)).toEqual(["c2"]);
    // "needs-approval" matches the LIVE pending-approval set, not a
    // status==='draft' heuristic (MV-application-tracker-002) — c3's draft
    // application has a pending ApprovalRequest (id "c3") here.
    const pendingApprovalIds = new Set(["c3"]);
    expect(
      cards.filter((c) => cardMatchesFilter(c, "needs-approval", pendingApprovalIds)).map((c) => c.id),
    ).toEqual(["c3"]);
    expect(cards.filter((c) => cardMatchesFilter(c, "all"))).toHaveLength(3);
  });

  it("needs-approval never disagrees with the pending-approvals banner (MV-application-tracker-002)", () => {
    // A draft application with NO linked pending ApprovalRequest (the
    // Stripe-repro scenario) must NOT show up under "Needs approval" —
    // the filter and the banner must always describe the same set.
    expect(cards.filter((c) => cardMatchesFilter(c, "needs-approval", new Set())).map((c) => c.id)).toEqual(
      [],
    );
    // A non-draft application that still has a live pending approval (e.g.
    // an email_send approval attached post-submission) DOES match — the
    // filter tracks the approval, not the status label.
    const submittedWithPendingApproval: StageCard = {
      id: "c4",
      title: "D",
      company: "Beta",
      updatedAt: "2026-07-07T00:00:00Z",
      fit: 60,
      app: app({ id: "c4", status: "submitted" }),
      meta: {},
    };
    expect(
      cardMatchesFilter(submittedWithPendingApproval, "needs-approval", new Set(["c4"])),
    ).toBe(true);
  });

  it("sorts by recency, fit and company without mutating input", () => {
    const original = [...cards];
    expect(sortCards(cards, "recent").map((c) => c.id)).toEqual(["c2", "c1", "c3"]);
    expect(sortCards(cards, "fit").map((c) => c.id)).toEqual(["c1", "c3", "c2"]);
    expect(sortCards(cards, "company").map((c) => c.id)).toEqual(["c2", "c3", "c1"]);
    expect(cards).toEqual(original);
  });

  it("viewStages applies both to every stage", () => {
    const stages = buildStages(
      [
        app({ id: "a1", status: "draft", fitScore: 90, updatedAt: "2026-07-09T00:00:00Z" }),
        app({ id: "a2", jobId: "j2", status: "draft", fitScore: 70, updatedAt: "2026-07-10T00:00:00Z" }),
      ],
      [],
    );
    const filtered = viewStages(stages, "high-fit", "fit");
    expect(filtered.find((s) => s.key === "ready")!.cards.map((c) => c.id)).toEqual(["a1"]);
  });

  // GAP-P4-050 regression guard: a filter that empties every card in a stage
  // must not remove that stage's column — the board always shows all 8.
  it("viewStages keeps all 8 columns mounted even when a filter matches nothing", () => {
    const stages = buildStages(
      [app({ id: "a1", jobId: "j1", status: "submitted", fitScore: 40 })],
      [],
    );
    const filtered = viewStages(stages, "high-fit", "recent");
    expect(filtered).toHaveLength(8);
    expect(filtered.map((s) => s.key)).toEqual(STAGE_DEFS.map((d) => d.key));
    expect(filtered.find((s) => s.key === "submitted")!.cards).toEqual([]);
  });
});

// ---- U5 — honest submission-state label helpers ----------------------------
//
// U-PLAN "U5 MANDATE SHARPENED" rule 1 (NO-PREPARED-ONLY): an approved
// application ends either TRANSMITTED (with checkable evidence) or in an
// HONEST, ACTIONABLE manual-step state. These three pure helpers are the only
// place the machine codes the backend records
// (apps/api/app/services/apply_channel_resolver.py CHANNELS,
// apply_executor.py `record_manual_step` reasons, and the shared
// transmissionChannel/transmissionRef columns) become the words the user
// reads, so the honesty rules live here and are pinned here.

describe("U5 channelLabel", () => {
  it("maps every known channel code to human copy", () => {
    expect(channelLabel("gmail")).toBe("email");
    expect(channelLabel("ashby")).toBe("Ashby application form");
    expect(channelLabel("greenhouse")).toBe("Greenhouse application form");
    expect(channelLabel("lever")).toBe("Lever application form");
    expect(channelLabel("smartrecruiters")).toBe("SmartRecruiters application form");
    expect(channelLabel("generic")).toBe("the employer's application form");
    expect(channelLabel("seek-manual")).toBe("Seek (not automated)");
    expect(channelLabel("unknown")).toBe("an unresolved channel");
  });

  it("never invents a channel when none was recorded", () => {
    expect(channelLabel(null)).toBe("the employer");
    expect(channelLabel(undefined)).toBe("the employer");
    expect(channelLabel("")).toBe("the employer");
  });

  it("shows an unrecognised code verbatim rather than hiding it", () => {
    // A channel this build has not been taught about must stay legible —
    // silently rendering it as a known channel would be a fabricated claim.
    expect(channelLabel("workday")).toBe("workday");
  });
});

describe("U5 manualStepLabel", () => {
  it("maps every reason the executor records to an actionable headline", () => {
    expect(manualStepLabel("unknown_required_question")).toBe(
      "A required question needs your answer",
    );
    expect(manualStepLabel("captcha")).toBe("A CAPTCHA blocked automatic submission");
    expect(manualStepLabel("login_wall")).toBe("This posting requires logging in to apply");
    expect(manualStepLabel("no_automatable_channel")).toBe(
      "No automatic submission path exists for this posting yet",
    );
    expect(manualStepLabel("submit_control_not_found")).toBe(
      "Aether filled the form but could not find its submit button",
    );
    expect(manualStepLabel("no_confirmation")).toBe(
      "Aether submitted the form but the site did not confirm it",
    );
    expect(manualStepLabel("verification_code_email")).toBe(
      "The employer emailed a verification code to finish this application",
    );
  });

  it("de-slugifies an unknown reason instead of hiding it behind a vague label", () => {
    expect(manualStepLabel("two_factor_challenge")).toBe("Two factor challenge");
  });

  it("falls back to a neutral headline when no reason was recorded", () => {
    expect(manualStepLabel(null)).toBe("Manual step needed");
    expect(manualStepLabel(undefined)).toBe("Manual step needed");
  });
});

// MED-8 (re-review): the manual-step tooltip title was assembled inline,
// identically, at both the board badge and the "ready" card badge — pinning
// the single-sourced helper here means a future drift shows up as a test
// change in ONE place, not a silent divergence in two.
describe("U5 manualStepTooltip", () => {
  it("quotes the employer's own verbatim detail when one was recorded", () => {
    expect(manualStepTooltip("captcha", "Please verify you are human")).toBe(
      'A CAPTCHA blocked automatic submission: "Please verify you are human"',
    );
  });

  it("falls back to the bare label when no detail was recorded", () => {
    expect(manualStepTooltip("login_wall", null)).toBe(
      "This posting requires logging in to apply",
    );
    expect(manualStepTooltip("login_wall", undefined)).toBe(
      "This posting requires logging in to apply",
    );
  });
});

// BLOCKER-2/BLOCKER-3 (re-review): the FE promised automatic employer-form
// submission for every non-email posting, unconditionally — false today (the
// ARQ sweep that would drive it is OFF by code default) and false by ruling
// for Seek and unresolved channels even once a deployment turns the sweep
// on. `notTransmittedReason` is the single place this differentiation lives.
describe("U5 notTransmittedReason", () => {
  it("points at Approvals when the posting has a real apply email", () => {
    expect(notTransmittedReason({ autoSubmittable: true, applyChannel: "email" })).toBe(
      "Approve it in Approvals to email it to the employer.",
    );
  });

  it("never promises automation for a Seek posting (ADR-SEEK-V3)", () => {
    const reason = notTransmittedReason({ autoSubmittable: false, applyChannel: "seek-manual" });
    expect(reason).toContain("does not automate Seek");
    expect(reason).not.toContain("automatically");
  });

  it("states honestly that site-apply is not enabled, for a resolved automatable channel, when the sweep is OFF", () => {
    const reason = notTransmittedReason({
      autoSubmittable: false,
      applyChannel: "ashby",
      sweepEnabled: false,
    });
    expect(reason).toContain("publishes no application email address");
    expect(reason).toContain("not enabled on this deployment yet");
    expect(reason).not.toContain("with no further action");
  });

  it("defaults to the sweep-OFF wording when sweepEnabled is omitted (today's deployment reality)", () => {
    const reason = notTransmittedReason({ autoSubmittable: false, applyChannel: "greenhouse" });
    expect(reason).toContain("not enabled on this deployment yet");
  });

  // SHOULD-FIX 6 (round-3 re-review): the "not enabled on this deployment
  // yet" claim used to be hardcoded with zero coupling to the real
  // AETHER_APPLY_SWEEP_ENABLED kill-switch — true today, false the moment an
  // operator turns the sweep on. Both renderings must be honest.
  it("states honestly that automatic submission WILL run, for a resolved automatable channel, when the sweep is ON", () => {
    const reason = notTransmittedReason({
      autoSubmittable: false,
      applyChannel: "greenhouse",
      sweepEnabled: true,
    });
    expect(reason).toContain("publishes no application email address");
    expect(reason).not.toContain("not enabled on this deployment yet");
    expect(reason).toMatch(/enabled|will submit|automatically/i);
  });

  it("never claims a channel for an unresolved or absent applyChannel", () => {
    expect(
      notTransmittedReason({ autoSubmittable: false, applyChannel: "unknown" }),
    ).toContain("has not resolved where to submit it");
    expect(
      notTransmittedReason({ autoSubmittable: false, applyChannel: null }),
    ).toContain("has not resolved where to submit it");
  });
});

// MUST-FIX 3/5 (round-3 re-review): the disclaimer used to instruct the user
// to "send each email individually from its card" — there is NO send
// affordance on an application's card, only `executeApproval`, which now
// fires automatically for every bulk-approved email_send item (C2). The
// disclaimer must describe THAT real behaviour, not a UI surface that does
// not exist, and must not contradict `notTransmittedReason`'s per-application
// copy (MUST-FIX 5). SHOULD-FIX 6: the employer-form half must read the live
// sweep signal exactly like `notTransmittedReason` does.
describe("U5 automaticSubmissionDisclaimer (bulk-approve confirm)", () => {
  it("never contradicts itself the way the pre-refix copy did", () => {
    const text = automaticSubmissionDisclaimer(false);
    expect(text).not.toContain("with no further action");
    expect(text).not.toContain("queued for automatic submission");
  });

  it("never tells the user to send from a card that has no send button", () => {
    expect(automaticSubmissionDisclaimer(false)).not.toContain("from each application's card");
    expect(automaticSubmissionDisclaimer(true)).not.toContain("from each application's card");
  });

  it("truthfully says approved emails ARE sent immediately (C2 fixed the behaviour to match)", () => {
    const text = automaticSubmissionDisclaimer(false);
    expect(text).toMatch(/email.*sen(d|t)/i);
    expect(text).not.toContain("does not send anything automatically");
  });

  it("says employer-form submission is not enabled yet, when the sweep is OFF", () => {
    expect(automaticSubmissionDisclaimer(false)).toContain("not enabled on this deployment yet");
  });

  // Round-4 MUST-FIX 1/2 re-verification: the disclaimer must describe the
  // resolved apply CHANNEL (an application whose posting publishes an address
  // is sent by this same click, not only an outreach `email_send`), and the
  // retry it points at must be the real `Retry send` button the Approvals
  // queue renders for an approved-but-unsent request (`needsSendRetry`).
  it("covers an application sent by email, not only outreach emails", () => {
    for (const text of [automaticSubmissionDisclaimer(false), automaticSubmissionDisclaimer(true)]) {
      expect(text).toMatch(/application whose posting publishes an application address/i);
    }
  });

  it("names the retry affordance that actually exists for a failed send", () => {
    expect(automaticSubmissionDisclaimer(false)).toContain("Retry send");
    expect(automaticSubmissionDisclaimer(true)).toContain("Retry send");
  });

  it("says employer-form submission WILL run, when the sweep is ON — never the OFF wording", () => {
    const text = automaticSubmissionDisclaimer(true);
    expect(text).not.toContain("not enabled on this deployment yet");
    expect(text).toMatch(/enabled|runs|will/i);
  });
});

describe("U5 describeTransmission", () => {
  it("describes the W-SUB email path with its findable Gmail message id", () => {
    const t = describeTransmission({
      transmittedTo: "careers@acme.com",
      transmittedAt: "2026-08-02T04:00:00Z",
      transmissionChannel: "gmail",
      transmissionRef: "gmail-msg-1",
    });
    expect(t.headline).toContain("Sent by Aether to careers@acme.com");
    expect(t.headline).toContain(shortDate("2026-08-02T04:00:00Z"));
    expect(t.evidenceNote).toBe("message gmail-msg-1 (in your Gmail Sent folder)");
    // A Gmail message id is not a URL — offering it as a link would be a
    // broken promise, so the email path never produces one.
    expect(t.evidenceUrl).toBeNull();
  });

  it("treats an absent channel as the email path (every pre-U5 row)", () => {
    const t = describeTransmission({
      transmittedTo: "jobs@acme.com",
      transmittedAt: null,
      transmissionChannel: null,
      transmissionRef: null,
    });
    expect(t.headline).toBe("Sent by Aether to jobs@acme.com");
    expect(t.evidenceUrl).toBeNull();
    expect(t.evidenceNote).toBeNull();
  });

  // MED-9 (re-review, latent fabrication risk): `transmissionChannel` is
  // stamped "gmail" today (application_submission.py `CHANNEL_GMAIL`), but
  // the resolver's OWN code for the same channel is "email"
  // (apply_channel_resolver.py). A future writer using "email" must still
  // render the honest email-path headline, not fall into the web-form
  // branch and claim a screenshot that was never taken.
  it("also treats transmissionChannel \"email\" as the email path", () => {
    const t = describeTransmission({
      transmittedTo: "jobs@acme.com",
      transmittedAt: "2026-08-13T09:00:00Z",
      transmissionChannel: "email",
      transmissionRef: "gmail-msg-2",
    });
    expect(t.headline).toBe(`Sent by Aether to jobs@acme.com on ${shortDate("2026-08-13T09:00:00Z")}`);
    expect(t.evidenceUrl).toBeNull();
    expect(t.evidenceNote).toBe("message gmail-msg-2 (in your Gmail Sent folder)");
  });

  it("names the real ATS form for a site submission", () => {
    const t = describeTransmission({
      transmittedTo: "https://jobs.ashbyhq.com/acme/1",
      transmittedAt: "2026-08-13T09:00:00Z",
      transmissionChannel: "ashby",
      transmissionRef: "https://jobs.ashbyhq.com/acme/1/confirmation",
    });
    expect(t.headline).toContain("Submitted by Aether via Ashby application form");
    expect(t.evidenceUrl).toBe("https://jobs.ashbyhq.com/acme/1/confirmation");
    expect(t.evidenceNote).toBeNull();
  });

  it("never links a server-side screenshot path — an unopenable link is not evidence", () => {
    const t = describeTransmission({
      transmittedTo: "https://boards.greenhouse.io/acme/jobs/1",
      transmittedAt: "2026-08-13T09:00:00Z",
      transmissionChannel: "greenhouse",
      transmissionRef: "/var/lib/aether/apply-evidence/app-1.png",
    });
    expect(t.evidenceUrl).toBeNull();
    expect(t.evidenceNote).toBe(
      "confirmation screenshot saved by Aether (not yet viewable in this app)",
    );
  });

  it("makes no evidence claim when no reference was stored", () => {
    const t = describeTransmission({
      transmittedTo: "https://jobs.lever.co/acme/1",
      transmittedAt: "2026-08-13T09:00:00Z",
      transmissionChannel: "lever",
      transmissionRef: null,
    });
    expect(t.headline).toContain("Submitted by Aether via Lever application form");
    expect(t.evidenceUrl).toBeNull();
    expect(t.evidenceNote).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ORCHESTRATOR RULING U5-F3 (2026-08-14, binding) — `lever` and
// `smartrecruiters` (and `generic`) left the automation allowlist: they had no
// dedicated form parser, so automating them meant a best-effort schema driving
// a real submit click on a real employer's form. They are ASSISTED channels
// now — Aether prepares the tailored résumé and cover letter and hands the
// user the direct link. The FE copy has to say exactly that, because the FE
// copy is what the user believes.
// ---------------------------------------------------------------------------
describe("U5-F3 assisted channels (lever / smartrecruiters / generic)", () => {
  it("says the artifacts are ready and that the platform needs the user's click", () => {
    for (const channel of ["lever", "smartrecruiters", "generic"]) {
      const reason = notTransmittedReason({ autoSubmittable: false, applyChannel: channel });
      expect(reason).toContain("ready to submit");
      expect(reason).toContain("needs your click");
      // The one thing it must never do is imply Aether will submit it later.
      expect(reason).not.toContain("not enabled on this deployment yet");
    }
  });

  it("names the platform instead of a vague 'the employer's site'", () => {
    expect(notTransmittedReason({ autoSubmittable: false, applyChannel: "lever" })).toContain(
      "Lever",
    );
    expect(
      notTransmittedReason({ autoSubmittable: false, applyChannel: "smartrecruiters" }),
    ).toContain("SmartRecruiters");
  });

  it("keeps the 'not enabled yet' wording ONLY for the two automatable channels, sweep OFF", () => {
    for (const channel of ["ashby", "greenhouse"]) {
      expect(
        notTransmittedReason({ autoSubmittable: false, applyChannel: channel, sweepEnabled: false }),
      ).toContain("not enabled on this deployment yet");
    }
  });

  it("assisted channels never mention deployment-enablement even when the sweep is ON — they are never automated", () => {
    for (const channel of ["lever", "smartrecruiters", "generic"]) {
      const reason = notTransmittedReason({
        autoSubmittable: false,
        applyChannel: channel,
        sweepEnabled: true,
      });
      expect(reason).toContain("needs your click");
      expect(reason).not.toContain("not enabled on this deployment yet");
    }
  });

  it("still distinguishes an unresolved posting from an assisted one", () => {
    expect(notTransmittedReason({ autoSubmittable: false, applyChannel: "unknown" })).toContain(
      "has not resolved where to submit it",
    );
  });
});

describe("U5 closing round — new manual-step reasons are legible", () => {
  it("labels the assisted-channel outcome as ready-for-your-click, not a failure", () => {
    expect(manualStepLabel("assisted_manual_submit")).toBe(
      "Ready to submit — this platform needs your click",
    );
  });

  it("labels an expired approval as reconfirmable, not as a broken submission", () => {
    expect(manualStepLabel("approval_expired")).toBe("Approval expired — reconfirm to submit");
  });
});
