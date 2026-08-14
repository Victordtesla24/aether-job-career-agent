// @vitest-environment jsdom
/**
 * U5d-2 — the per-card submit control (USER MANDATE 2026-08-14).
 *
 * All transport is MOCKED. Nothing in this file can reach a network, a
 * browser-automation seam or an email provider — the two real transmission
 * entry points (`playwright_form_submitter` on the backend and the Gmail send
 * behind `transmit_application`) live in the API process and are asserted
 * unreached by the backend suites; here the assertion is the client-side half:
 * the ONLY two endpoints this control may ever call are
 * `POST /applications/{id}/request-submission` and the EXISTING
 * `POST /approvals/{id}/execute`. A third call, or a private submit route,
 * fails these tests.
 *
 * The load-bearing invariant: the card reaches "Submitted ✓" if and only if a
 * RE-READ application row carries a real `transmittedAt`. A transport that
 * answers `{transmitted: true}` without the row agreeing must not paint one.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SubmissionControl from "../SubmissionControl";
import {
  cardStateFor,
  hasTransmissionProof,
  runCardSubmission,
} from "../submission-control-lib";
import type { Application, SubmissionControl as ControlBlock } from "../../../lib/api/applications";

function control(overrides: Partial<ControlBlock> = {}): ControlBlock {
  return {
    state: "ready",
    action: "submit",
    label: "Submit application",
    detail: "Aether can complete this Ashby application for you.",
    channel: "ashby",
    applyUrl: "https://jobs.ashbyhq.com/example-co/abc",
    href: null,
    missing: [],
    ...overrides,
  };
}

function app(overrides: Partial<Application> = {}): Application {
  return {
    id: "capp1",
    jobId: "cjob1",
    resumeId: "cres1",
    status: "draft",
    jobTitle: "Finance Specialist",
    company: "Example Co",
    createdAt: "2026-08-14T00:00:00Z",
    updatedAt: "2026-08-14T00:00:00Z",
    transmittedAt: null,
    transmissionRef: null,
    submissionControl: control(),
    ...overrides,
  } as Application;
}

describe("U5d-2 card state vocabulary", () => {
  it("renders the server's state, never one it invented", () => {
    expect(cardStateFor(control({ state: "needs_your_click" }))).toBe("needs_your_click");
    expect(cardStateFor(control({ state: "manual_step" }))).toBe("manual_step");
    expect(cardStateFor(control({ state: "expired_reconfirm" }))).toBe("expired_reconfirm");
  });

  it("lets the local state add submitting/failed and nothing else", () => {
    expect(cardStateFor(control(), "submitting")).toBe("submitting");
    expect(cardStateFor(control(), "failed")).toBe("failed");
    // The one direction that must be closed: local state can never upgrade a
    // card to submitted.
    expect(cardStateFor(control({ state: "ready" }), "idle")).toBe("ready");
  });

  it("treats a missing control as draft rather than throwing", () => {
    expect(cardStateFor(null)).toBe("draft");
    expect(cardStateFor(undefined)).toBe("draft");
  });

  it("proves transmission ONLY from transmittedAt", () => {
    expect(hasTransmissionProof({ transmittedAt: "2026-08-14T09:00:00Z" })).toBe(true);
    expect(hasTransmissionProof({ transmittedAt: null })).toBe(false);
    expect(hasTransmissionProof(null)).toBe(false);
  });
});

describe("U5d-2 click sequence", () => {
  it("approves then executes through the EXISTING endpoints, in that order", async () => {
    const calls: string[] = [];
    const outcome = await runCardSubmission("capp1", {
      requestSubmission: async (id) => {
        calls.push(`request:${id}`);
        return {
          approvalId: "cappr1",
          applicationId: id,
          channel: "ashby",
          transmitted: false as const,
          detail: "recorded",
        };
      },
      executeApproval: async (approvalId) => {
        calls.push(`execute:${approvalId}`);
        return { status: "transmitted", transmitted: true };
      },
      fetchApplication: async (id) => {
        calls.push(`read:${id}`);
        return app({ transmittedAt: "2026-08-14T09:00:00Z", transmissionRef: "e.png" });
      },
    });

    expect(calls).toEqual(["request:capp1", "execute:cappr1", "read:capp1"]);
    expect(outcome.kind).toBe("transmitted");
  });

  it("refuses to report a transmission the re-read row cannot prove", async () => {
    const outcome = await runCardSubmission("capp1", {
      requestSubmission: async () => ({
        approvalId: "cappr1",
        applicationId: "capp1",
        channel: "ashby",
        transmitted: false as const,
        detail: "recorded",
      }),
      // A LYING transport: it claims success.
      executeApproval: async () => ({ status: "transmitted", transmitted: true }),
      // …but the row has no proof.
      fetchApplication: async () => app({ transmittedAt: null }),
    });

    expect(outcome.kind).toBe("failed");
    expect(outcome.kind === "failed" && outcome.detail).toMatch(/cannot show evidence/i);
  });

  it("surfaces a manual step honestly instead of as a failure or a success", async () => {
    const outcome = await runCardSubmission("capp1", {
      requestSubmission: async () => ({
        approvalId: "cappr1",
        applicationId: "capp1",
        channel: "ashby",
        transmitted: false as const,
        detail: "recorded",
      }),
      executeApproval: async () => ({
        status: "manual_step",
        transmitted: false,
        reason: "captcha",
        detail: "This form is protected by a CAPTCHA.",
      }),
      fetchApplication: async () =>
        app({ transmittedAt: null, manualStepReason: "captcha" }),
    });

    expect(outcome.kind).toBe("manual_step");
    expect(outcome.kind === "manual_step" && outcome.reason).toBe("captcha");
  });

  it("never executes when recording the approval failed", async () => {
    const execute = vi.fn(async () => ({ status: "transmitted", transmitted: true }));
    const outcome = await runCardSubmission("capp1", {
      requestSubmission: async () => {
        throw new Error("Aether does not auto-submit on this platform.");
      },
      executeApproval: execute,
      fetchApplication: async () => app(),
    });

    expect(execute).not.toHaveBeenCalled();
    expect(outcome.kind).toBe("failed");
    expect(outcome.kind === "failed" && outcome.detail).toMatch(/auto-submit/);
  });

  it("reports an execute failure honestly and claims nothing", async () => {
    const read = vi.fn(async () => app());
    const outcome = await runCardSubmission("capp1", {
      requestSubmission: async () => ({
        approvalId: "cappr1",
        applicationId: "capp1",
        channel: "ashby",
        transmitted: false as const,
        detail: "recorded",
      }),
      executeApproval: async () => {
        throw new Error("Approval already executed — no action taken.");
      },
      fetchApplication: read,
    });

    expect(outcome.kind).toBe("failed");
    expect(outcome.kind === "failed" && outcome.detail).toMatch(/already executed/);
    expect(read).not.toHaveBeenCalled();
  });
});

describe("U5d-2 rendered control", () => {
  it("offers Submit application on an automatable ready card", () => {
    render(<SubmissionControl application={app()} />);
    expect(screen.getByTestId("submission-control").dataset.state).toBe("ready");
    expect(screen.getByTestId("submission-control-button").textContent).toBe(
      "Submit application",
    );
  });

  it("offers the direct posting URL on an ASSISTED card, with no submit button", () => {
    render(
      <SubmissionControl
        application={app({
          submissionControl: control({
            state: "needs_your_click",
            action: "open_posting",
            label: "Ready to submit — open posting",
            channel: "lever",
            applyUrl: "https://jobs.lever.co/example-co/xyz",
          }),
        })}
      />,
    );
    expect(screen.queryByTestId("submission-control-button")).toBeNull();
    const link = screen.getByTestId("submission-control-link");
    expect(link.getAttribute("href")).toBe("https://jobs.lever.co/example-co/xyz");
  });

  it("offers Send application email on the email channel", () => {
    render(
      <SubmissionControl
        application={app({
          submissionControl: control({
            action: "send_email",
            label: "Send application email",
            channel: "email",
          }),
        })}
      />,
    );
    expect(screen.getByTestId("submission-control-button").textContent).toBe(
      "Send application email",
    );
  });

  it("says what is missing and links there when the artifacts are not ready", () => {
    render(
      <SubmissionControl
        application={app({
          submissionControl: control({
            state: "draft",
            action: "fix_artifacts",
            label: "Tailor resume first",
            href: "/dashboard/resume?job=cjob1",
            missing: ["tailoredResume"],
          }),
        })}
      />,
    );
    const fix = screen.getByTestId("submission-control-fix");
    expect(fix.textContent).toContain("Tailor resume first");
    expect(fix.getAttribute("href")).toBe("/dashboard/resume?job=cjob1");
  });

  it("surfaces a manual-step obstacle honestly", () => {
    render(
      <SubmissionControl
        application={app({
          submissionControl: control({
            state: "manual_step",
            action: "open_posting",
            label: "Needs a manual step",
            detail: "The form is protected by a CAPTCHA.",
            channel: "ashby",
          }),
        })}
      />,
    );
    expect(screen.getByTestId("submission-control").dataset.state).toBe("manual_step");
    expect(screen.getByTestId("submission-control-detail").textContent).toContain(
      "CAPTCHA",
    );
  });

  it("offers a one-click reconfirm for an aged-out approval", () => {
    const onReconfirm = vi.fn();
    render(
      <SubmissionControl
        application={app({
          submissionControl: control({
            state: "expired_reconfirm",
            action: "reconfirm",
            label: "Reconfirm to submit",
          }),
        })}
        onReconfirm={onReconfirm}
      />,
    );
    fireEvent.click(screen.getByTestId("submission-control-reconfirm"));
    expect(onReconfirm).toHaveBeenCalledTimes(1);
  });

  it("shows Submitted ✓ ONLY for the server's proof-bound state", () => {
    render(
      <SubmissionControl
        application={app({
          transmittedAt: "2026-08-14T09:00:00Z",
          submissionControl: control({
            state: "submitted",
            action: "none",
            label: "Submitted ✓",
            detail: "Aether transmitted this application — evidence: e.png",
          }),
        })}
      />,
    );
    expect(screen.getByTestId("submission-control").dataset.state).toBe("submitted");
    expect(screen.getByTestId("submission-control-label").textContent).toBe("Submitted ✓");
  });

  it("never says Submitted for a status='submitted' row with no proof", () => {
    render(
      <SubmissionControl
        application={app({
          status: "submitted",
          transmittedAt: null,
          submissionControl: control({
            state: "recorded_not_transmitted",
            action: "none",
            label: "Recorded — not transmitted",
            detail: "Aether has no evidence it transmitted anything.",
          }),
        })}
      />,
    );
    const node = screen.getByTestId("submission-control");
    expect(node.dataset.state).toBe("recorded_not_transmitted");
    expect(node.textContent).not.toContain("Submitted ✓");
  });

  it("shows honest in-flight progress and then an honest failure reason", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    render(
      <SubmissionControl
        application={app()}
        deps={{
          requestSubmission: async () => {
            await gate;
            return {
              approvalId: "cappr1",
              applicationId: "capp1",
              channel: "ashby",
              transmitted: false as const,
              detail: "recorded",
            };
          },
          executeApproval: async () => {
            throw new Error("The employer's site could not be reached.");
          },
          fetchApplication: async () => app(),
        }}
      />,
    );

    fireEvent.click(screen.getByTestId("submission-control-button"));
    await waitFor(() =>
      expect(screen.getByTestId("submission-control").dataset.state).toBe("submitting"),
    );
    release();
    await waitFor(() =>
      expect(screen.getByTestId("submission-control").dataset.state).toBe("failed"),
    );
    expect(screen.getByTestId("submission-control-detail").textContent).toContain(
      "could not be reached",
    );
  });

  it("does not paint success itself — it hands the outcome back for a server re-read", async () => {
    const onSettled = vi.fn();
    render(
      <SubmissionControl
        application={app()}
        onSettled={onSettled}
        deps={{
          requestSubmission: async () => ({
            approvalId: "cappr1",
            applicationId: "capp1",
            channel: "ashby",
            transmitted: false as const,
            detail: "recorded",
          }),
          executeApproval: async () => ({ status: "transmitted", transmitted: true }),
          fetchApplication: async () =>
            app({ transmittedAt: "2026-08-14T09:00:00Z", transmissionRef: "e.png" }),
        }}
      />,
    );

    fireEvent.click(screen.getByTestId("submission-control-button"));
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(onSettled.mock.calls[0][0].kind).toBe("transmitted");
    // The card itself is back to the SERVER's state — it did not self-promote.
    expect(screen.getByTestId("submission-control").dataset.state).toBe("ready");
  });
});
