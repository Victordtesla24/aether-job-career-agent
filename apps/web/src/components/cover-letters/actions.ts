/**
 * Enablement rules for the Cover Letter Studio actions panel.
 *
 * GAP-P4-043: the "Request Changes" control is a disclosure toggle — clicking it
 * only reveals/hides the change-request form, it mutates nothing. It must stay
 * interactive whenever a letter is selected, even while a Regenerate or refine
 * runs in the background. Gating it on the busy state made a slow regenerate
 * leave the button disabled, so a click hit Playwright's actionability timeout
 * and the control read as dead. Only the mutating actions (Regenerate, and the
 * form's submit) are gated on busy so they cannot race.
 */
export interface ActionsState {
  /** A letter is selected (the rail is bound to it). */
  hasSelection: boolean;
  /** A full agent re-run (Regenerate) is in flight. */
  regenerating: boolean;
  /** A refine / change-request redraft is in flight. */
  refining: boolean;
  /** A PDF export is in flight. */
  exporting: boolean;
  /** The change-request textarea has non-whitespace content. */
  hasInstructions: boolean;
}

/** A mutating action (Regenerate / refine) is in flight. */
function isBusy(s: Pick<ActionsState, "regenerating" | "refining">): boolean {
  return s.regenerating || s.refining;
}

/**
 * The Request-Changes disclosure toggle. Available whenever a letter is
 * selected — deliberately NOT gated on the busy state (see file header).
 */
export function changeRequestToggleDisabled(s: Pick<ActionsState, "hasSelection">): boolean {
  return !s.hasSelection;
}

/** Regenerate fires a network mutation, so it is gated on the busy state. */
export function regenerateDisabled(s: ActionsState): boolean {
  return !s.hasSelection || isBusy(s);
}

/** Submitting a change request fires a network mutation and needs instructions. */
export function changeRequestSubmitDisabled(s: ActionsState): boolean {
  return isBusy(s) || !s.hasInstructions;
}

/** Export is gated only on its own in-flight state. */
export function exportDisabled(s: Pick<ActionsState, "hasSelection" | "exporting">): boolean {
  return !s.hasSelection || s.exporting;
}
