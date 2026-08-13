// @vitest-environment jsdom
/**
 * U-UI AGENTS-PHANTOM-OVERFLOW-01 / AGENTS-CARD-OVERLAP-01 regression guard.
 *
 * Live audit: 70 elements across the 22 agent cards had scrollHeight >>
 * clientHeight because each card's hover-description popover stayed in the
 * DOM (opacity-0, `.group`/`group-hover`) even while closed, nested inside
 * the card. The fix renders the description through a portal to
 * document.body — never a descendant of the card — with visibility toggled
 * by CSS (matching MetricTooltip's proven `hidden opacity-0` <->
 * `opacity-100` pattern) rather than by conditional mounting, so it can no
 * longer inflate the card's or the section's scrollable-overflow region and
 * can never land in the same DOM position as another card's description.
 *
 * See also agent-card-hover-description.test.tsx for the structural
 * DOM-nesting contract this design was built against.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AgentConfigGrid from "../AgentConfigGrid";
import type { CatalogAgent } from "../api";

afterEach(() => cleanup());

function agent(key: string, name: string, tip: string): CatalogAgent {
  return {
    key,
    name,
    icon: "fa-robot",
    accent: "indigo",
    model: "n/a",
    recommended: "deterministic",
    tip,
    runnable: false,
    backend: null,
    enabled: true,
    // "planned" keeps the fixture light (skips AgentModelPicker/API-backed
    // children) — the recommendation tooltip renders regardless of status.
    status: "planned",
    modelOverridable: false,
    last_run: null,
  };
}

const AGENTS: CatalogAgent[] = [
  agent("jobDiscovery", "Job Discovery", "Finds new postings across every connected source."),
  agent("submission", "Submission", "Submits applications once you approve them."),
  agent("interviewPrep", "Interview Prep", "Preps talking points from the job description."),
];

const gridProps = {
  counts: { total: AGENTS.length, active: 0, paused: 0, error: 0, planned: AGENTS.length },
  loading: false,
  busyKey: null,
  onToggle: () => undefined,
  onRun: () => undefined,
  catalogModels: null,
  catalogLoading: false,
  catalogError: null,
  // REV-U-UI-04: required props — explicit for this fixture (no Orchestrator
  // card in AGENTS), not silently defaulted by the component.
  orchestratorModels: null,
  orchestratorModelsLoading: false,
  orchestratorModelsError: null,
  catalogRefreshedAt: null,
  catalogStale: false,
  catalogRefreshing: false,
  onRefreshCatalog: () => undefined,
  savingModelKey: null,
  onSelectModel: () => undefined,
};

describe("AgentConfigGrid recommendation tooltip (U-UI AGENTS-PHANTOM-OVERFLOW-01)", () => {
  it("is hidden (display:none) at rest, even though it's always in the DOM", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const popover = screen.getByTestId("agent-tip-popover-jobDiscovery");
    expect(popover.className).toMatch(/\bhidden\b/);
    expect(popover.className).toMatch(/opacity-0/);
  });

  it("becomes visible (with the right copy) while its trigger is hovered, and hides again on mouse leave", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const trigger = screen.getByTestId("agent-tip-jobDiscovery");
    const popover = screen.getByTestId("agent-tip-popover-jobDiscovery");
    expect(popover.textContent).toMatch(/Finds new postings/);

    fireEvent.mouseEnter(trigger);
    expect(popover.className).toMatch(/opacity-100/);
    expect(popover.className).not.toMatch(/\bhidden\b/);

    fireEvent.mouseLeave(trigger);
    expect(popover.className).toMatch(/\bhidden\b/);
    expect(popover.className).toMatch(/opacity-0/);
  });

  it("becomes visible on keyboard focus and hides again on Escape, returning focus to the trigger", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const trigger = screen.getByTestId("agent-tip-submission");
    const popover = screen.getByTestId("agent-tip-popover-submission");

    // A real `.focus()` call (not `fireEvent.focus`, which only dispatches
    // the event without moving `document.activeElement`) — needed so the
    // Escape handler's own re-focus below is a no-op, not a fresh focus
    // event that would reopen the popover, matching MetricTooltip's proven
    // Escape-close-refocus test pattern.
    act(() => trigger.focus());
    expect(popover.className).toMatch(/opacity-100/);

    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(popover.className).toMatch(/\bhidden\b/);
    expect(document.activeElement).toBe(trigger);
  });

  it("renders the description outside the card's own DOM subtree (portaled), so it can never overlap a neighbouring card's box", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const card = screen.getByTestId("agent-card-jobDiscovery");
    const popover = screen.getByTestId("agent-tip-popover-jobDiscovery");
    expect(card.contains(popover)).toBe(false);
  });
});

describe("AgentConfigGrid recommendation tooltip position (REV-U-UI-01)", () => {
  // The dashboard grid is window-scrolled (no inner scroll container), so a
  // fixed-position popover measured once on mount stays pinned to its
  // page-load coordinates forever — off-screen for any card below the
  // initial fold. jsdom reports all-zero rects, so the resulting pixel
  // position isn't assertable here, but the fix's observable *behaviour* —
  // re-measuring on open, and tracking the trigger while the popover stays
  // open — is: this pins that contract via the window listeners it wires.
  it("re-measures on open and tracks scroll/resize while open, cleaning up on close", () => {
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");

    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const trigger = screen.getByTestId("agent-tip-jobDiscovery");

    fireEvent.mouseEnter(trigger);
    expect(addSpy).toHaveBeenCalledWith("scroll", expect.any(Function), expect.objectContaining({ capture: true }));
    expect(addSpy).toHaveBeenCalledWith("resize", expect.any(Function), expect.objectContaining({ passive: true }));

    fireEvent.mouseLeave(trigger);
    expect(removeSpy).toHaveBeenCalledWith("scroll", expect.any(Function), true);
    expect(removeSpy).toHaveBeenCalledWith("resize", expect.any(Function));

    addSpy.mockRestore();
    removeSpy.mockRestore();
  });
});
