// @vitest-environment jsdom
/**
 * U-UI AGENTS-PHANTOM-OVERFLOW-01 / AGENTS-CARD-OVERLAP-01 regression guard.
 *
 * Live audit: 70 elements across the 22 agent cards had scrollHeight >>
 * clientHeight because each card's hover-description popover stayed in the
 * DOM (opacity-0, `.group`/`group-hover`) even while closed, and two
 * adjacent cards' hidden popover boxes geometrically overlapped at rest.
 * The fix renders the popover through a portal, mounted only while
 * hovered/focused — a closed tooltip contributes nothing to any card's DOM
 * at all, so there is nothing to overflow or overlap.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

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
  it("contributes zero popover DOM nodes at rest across all cards", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    // The exact defect: 70 always-present hidden popover boxes across 22
    // cards inflated ancestor scrollHeight even though nothing was hovered.
    expect(document.querySelectorAll('[data-testid^="agent-tip-popover-"]').length).toBe(0);
  });

  it("mounts the popover (with the right copy) only while its trigger is hovered, then removes it again", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const trigger = screen.getByTestId("agent-tip-jobDiscovery");

    expect(screen.queryByTestId("agent-tip-popover-jobDiscovery")).toBeNull();

    fireEvent.mouseEnter(trigger);
    const popover = screen.getByTestId("agent-tip-popover-jobDiscovery");
    expect(popover.textContent).toMatch(/Finds new postings/);

    fireEvent.mouseLeave(trigger);
    expect(screen.queryByTestId("agent-tip-popover-jobDiscovery")).toBeNull();
  });

  it("mounts the popover on keyboard focus and removes it on blur / Escape", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const trigger = screen.getByTestId("agent-tip-submission");

    // A real `.focus()` call (not `fireEvent.focus`, which only dispatches
    // the event without moving `document.activeElement`) — needed so the
    // Escape handler's own re-focus below is a no-op, not a fresh focus
    // event that would reopen the popover, matching MetricTooltip's proven
    // Escape-close-refocus test pattern.
    act(() => trigger.focus());
    expect(screen.getByTestId("agent-tip-popover-submission")).not.toBeNull();

    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByTestId("agent-tip-popover-submission")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("renders the open popover outside the card's own DOM subtree (portaled), so it can never overlap a neighbouring card's box", () => {
    render(<AgentConfigGrid agents={AGENTS} {...gridProps} />);
    const card = screen.getByTestId("agent-card-jobDiscovery");
    fireEvent.mouseEnter(screen.getByTestId("agent-tip-jobDiscovery"));

    const popover = screen.getByTestId("agent-tip-popover-jobDiscovery");
    expect(card.contains(popover)).toBe(false);
  });
});
