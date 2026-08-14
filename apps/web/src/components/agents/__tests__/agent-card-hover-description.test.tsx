// @vitest-environment jsdom
/**
 * MON-018 / U-UI — AGENTS-PHANTOM-OVERFLOW-01 / AGENTS-CARD-OVERLAP-01.
 *
 * Live audit on /dashboard/agents (1440x900, baseline — no hover, no bell
 * open): the recommendation tooltip on EVERY one of the 22 agent cards
 * (components/agents/AgentConfigGrid.tsx `AgentCard`) is an inline,
 * non-portaled `<span role="tooltip">` living inside
 * `span.group.relative` — `position:absolute` but still a DOM descendant of
 * the card. Measured: that wrapper span reports scrollHeight 122 vs
 * clientHeight 20 (the hidden description box inflates the nearest
 * positioned ancestor's scrollable-overflow region even though nothing is
 * visibly clipped today because every ancestor currently has
 * `overflow: visible`). It cascades all the way up:
 * section[data-testid=agent-configuration] reports scrollHeight 2926 vs
 * clientHeight 2855 (71px phantom overflow). AGENTS-CARD-OVERLAP-01 also
 * found two adjacent cards' hidden description boxes geometrically
 * overlapping at rest (Submission ↔ Interview-Prep, 224×19px = 4172px²).
 *
 * Fix direction named by the audit: portal the description out of the
 * card's DOM subtree (the same `createPortal(..., document.body)` pattern
 * already used in components/offers/AddOfferModal.tsx for an analogous
 * "must not be constrained by an ancestor" problem) — or any fixed-position
 * strategy with measured placement — as long as the description node is no
 * longer a descendant of the card, so it can never again contribute to that
 * card's (or the section's) scrollable-overflow region.
 *
 * jsdom does not compute scrollHeight/clientHeight from real layout, so the
 * audit's exact pixel deltas aren't reproducible here — this pins the
 * FIXABLE structural contract instead: the description tooltip's DOM node
 * must not be a descendant of its `agent-card-<key>` container. This fails
 * today because the tooltip is rendered inline as a sibling of the trigger
 * button, inside the card.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AgentConfigGrid from "../AgentConfigGrid";
import type { CatalogAgent } from "../api";

const AGENT_A: CatalogAgent = {
  key: "submission",
  name: "Submission",
  icon: "fa-paper-plane",
  accent: "indigo",
  model: "claude-sonnet-5",
  recommended: "claude-sonnet-5",
  tip: "SUBMISSION-CARD-TIP-TEXT",
  runnable: true,
  backend: "submission",
  enabled: true,
  status: "active",
  modelOverridable: true,
  last_run: null,
};

const AGENT_B: CatalogAgent = {
  key: "interviewPrep",
  name: "Interview Prep",
  icon: "fa-comments",
  accent: "coral",
  model: "claude-sonnet-5",
  recommended: "claude-sonnet-5",
  tip: "INTERVIEW-PREP-CARD-TIP-TEXT",
  runnable: true,
  backend: "interviewPrep",
  enabled: true,
  status: "active",
  modelOverridable: true,
  last_run: null,
};

function renderGrid() {
  return render(
    <AgentConfigGrid
      agents={[AGENT_A, AGENT_B]}
      counts={{ total: 2, active: 2, paused: 0, error: 0, planned: 0 }}
      loading={false}
      busyKey={null}
      onToggle={vi.fn()}
      onRun={vi.fn()}
      catalogModels={[]}
      catalogLoading={false}
      catalogError={null}
      // REV-U-UI-04: required props — explicit for this fixture (no
      // Orchestrator card among AGENT_A/AGENT_B), not silently defaulted.
      orchestratorModels={null}
      orchestratorModelsLoading={false}
      orchestratorModelsError={null}
      catalogRefreshedAt={null}
      catalogStale={false}
      catalogRefreshing={false}
      onRefreshCatalog={vi.fn()}
      savingModelKey={null}
      onSelectModel={vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
});

describe("Agent-card hover description (AGENTS-PHANTOM-OVERFLOW-01)", () => {
  it("renders the recommendation description outside the card's DOM subtree (portal/fixed-position), not nested inside it", () => {
    renderGrid();
    const card = screen.getByTestId("agent-card-submission");
    const description = screen.getByText("SUBMISSION-CARD-TIP-TEXT");

    // Today this is false: the tooltip span is a literal descendant of the
    // card (span.group.relative > span[role=tooltip]), which is exactly
    // what lets its hidden box inflate the card's scrollable-overflow
    // region per the audit's scrollHeight/clientHeight measurement.
    expect(card.contains(description)).toBe(false);
  });

  it("does not let two adjacent cards' hidden descriptions land in the same portal/DOM position such that they could overlap (AGENTS-CARD-OVERLAP-01) — each description carries its own agent-key identity", () => {
    renderGrid();
    const descA = screen.getByText("SUBMISSION-CARD-TIP-TEXT");
    const descB = screen.getByText("INTERVIEW-PREP-CARD-TIP-TEXT");

    // Whatever portal root the fix uses, each description must be
    // independently identifiable (so a future placement algorithm can
    // position it per-trigger rather than two descriptions ever sharing
    // one blind, unmeasured absolute position). Pinned via a per-agent
    // testid on the description node itself.
    expect(descA.closest('[data-testid="agent-tip-desc-submission"]')).not.toBeNull();
    expect(descB.closest('[data-testid="agent-tip-desc-interviewPrep"]')).not.toBeNull();
  });
});
