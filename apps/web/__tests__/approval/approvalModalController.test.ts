import { describe, it, expect, vi } from "vitest";
import {
  ApprovalModalController,
  createApprovalModalController,
  APPROVAL_IDS,
  FOCUS_ORDER,
} from "../../src/components/approval/approvalModalController.js";
import { SAMPLE_APPROVAL_REQUEST } from "../../src/components/approval/fixtures.js";
import type { ApprovalDecisionPayload } from "../../src/components/approval/types.js";

function make(overrides: Partial<Parameters<typeof createApprovalModalController>[0]> = {}) {
  const submit = vi.fn(async (_p: ApprovalDecisionPayload) => {});
  const controller = createApprovalModalController({ submit, ...overrides });
  return { controller, submit };
}

describe("ApprovalModalController lifecycle", () => {
  it("starts closed", () => {
    const { controller } = make();
    expect(controller.status).toBe("closed");
    expect(controller.isOpen).toBe(false);
    expect(controller.getSnapshot().request).toBeNull();
  });

  it("opens with a request and resets transient state", () => {
    const { controller } = make();
    controller.toggleTrust(true); // no-op while closed
    controller.open(SAMPLE_APPROVAL_REQUEST);
    const s = controller.getSnapshot();
    expect(s.status).toBe("open");
    expect(s.request).toEqual(SAMPLE_APPROVAL_REQUEST);
    expect(s.trustAgent).toBe(false);
    expect(s.decision).toBeNull();
    expect(s.error).toBeNull();
  });

  it("notifies subscribers on state change and unsubscribes cleanly", () => {
    const { controller } = make();
    const listener = vi.fn();
    const unsub = controller.subscribe(listener);
    controller.open(SAMPLE_APPROVAL_REQUEST);
    expect(listener).toHaveBeenCalledTimes(1);
    unsub();
    controller.close();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("toggleTrust flips and accepts an explicit value", () => {
    const { controller } = make();
    controller.open(SAMPLE_APPROVAL_REQUEST);
    controller.toggleTrust();
    expect(controller.getSnapshot().trustAgent).toBe(true);
    controller.toggleTrust(false);
    expect(controller.getSnapshot().trustAgent).toBe(false);
  });
});

describe("decisions", () => {
  it("approve submits the correct payload and resolves", async () => {
    const { controller, submit } = make();
    const onResolved = vi.fn();
    const c2 = createApprovalModalController({ submit, onResolved });
    c2.open(SAMPLE_APPROVAL_REQUEST);
    c2.toggleTrust(true);
    await c2.approve();
    expect(submit).toHaveBeenCalledWith({
      taskId: SAMPLE_APPROVAL_REQUEST.taskId,
      decision: "approve",
      trustAgent: true,
    });
    expect(c2.getSnapshot().status).toBe("resolved");
    expect(c2.getSnapshot().decision).toBe("approve");
    expect(onResolved).toHaveBeenCalledWith("approve", SAMPLE_APPROVAL_REQUEST);
    void controller;
  });

  it("reject and editApprove send their decision", async () => {
    const { controller, submit } = make();
    controller.open(SAMPLE_APPROVAL_REQUEST);
    await controller.reject();
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ decision: "reject" }),
    );
    controller.open(SAMPLE_APPROVAL_REQUEST);
    await controller.editApprove();
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ decision: "edit" }),
    );
  });

  it("surfaces a submit error and stays open for retry", async () => {
    const submit = vi.fn(async (_p: ApprovalDecisionPayload): Promise<void> => {
      throw new Error("network down");
    });
    const controller = new ApprovalModalController({ submit });
    controller.open(SAMPLE_APPROVAL_REQUEST);
    await controller.approve();
    const s = controller.getSnapshot();
    expect(s.status).toBe("error");
    expect(s.error).toBe("network down");
    // Retry is allowed from the error state.
    submit.mockResolvedValueOnce(undefined);
    await controller.approve();
    expect(controller.getSnapshot().status).toBe("resolved");
  });

  it("ignores a decision when there is no request", async () => {
    const { controller, submit } = make();
    await controller.approve();
    expect(submit).not.toHaveBeenCalled();
  });

  it("prevents double-submit while a decision is in flight", async () => {
    let release!: () => void;
    const submit = vi.fn(
      () => new Promise<void>((res) => (release = res)),
    );
    const controller = new ApprovalModalController({ submit });
    controller.open(SAMPLE_APPROVAL_REQUEST);
    const first = controller.approve();
    controller.reject(); // should be ignored — in flight
    expect(controller.status).toBe("submitting");
    release();
    await first;
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("cannot be dismissed while submitting", async () => {
    let release!: () => void;
    const submit = vi.fn(() => new Promise<void>((res) => (release = res)));
    const controller = new ApprovalModalController({ submit });
    controller.open(SAMPLE_APPROVAL_REQUEST);
    const p = controller.approve();
    controller.close();
    expect(controller.status).toBe("submitting");
    release();
    await p;
    expect(controller.status).toBe("resolved");
  });
});

describe("accessibility & keyboard", () => {
  it("exposes correct ARIA dialog props", () => {
    const { controller } = make();
    expect(controller.getAriaProps()).toEqual({
      role: "dialog",
      "aria-modal": true,
      "aria-labelledby": APPROVAL_IDS.title,
      "aria-describedby": APPROVAL_IDS.description,
    });
  });

  it("defaults initial focus to approve and honours override", () => {
    const { controller } = make();
    expect(controller.getInitialFocusId()).toBe(APPROVAL_IDS.approve);
    const { controller: c2 } = make({ initialFocus: "close" });
    expect(c2.getInitialFocusId()).toBe(APPROVAL_IDS.close);
  });

  it("wraps focus forward and backward through the trap", () => {
    const { controller } = make();
    const last = FOCUS_ORDER[FOCUS_ORDER.length - 1];
    expect(controller.nextFocusId(last)).toBe(FOCUS_ORDER[0]);
    expect(controller.nextFocusId(FOCUS_ORDER[0], true)).toBe(last);
    expect(controller.nextFocusId(FOCUS_ORDER[0])).toBe(FOCUS_ORDER[1]);
    expect(controller.nextFocusId("unknown-id")).toBe(FOCUS_ORDER[0]);
  });

  it("Escape closes an open modal and consumes the event", () => {
    const { controller } = make();
    controller.open(SAMPLE_APPROVAL_REQUEST);
    expect(controller.handleKeydown("Escape")).toBe(true);
    expect(controller.status).toBe("closed");
  });

  it("Tab is consumed to keep the trap; other keys are not", () => {
    const { controller } = make();
    controller.open(SAMPLE_APPROVAL_REQUEST);
    expect(controller.handleKeydown("Tab")).toBe(true);
    expect(controller.handleKeydown("a")).toBe(false);
  });

  it("keydown is inert when closed", () => {
    const { controller } = make();
    expect(controller.handleKeydown("Escape")).toBe(false);
  });
});
