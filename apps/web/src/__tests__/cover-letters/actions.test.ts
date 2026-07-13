import { describe, expect, it } from "vitest";

import {
  changeRequestSubmitDisabled,
  changeRequestToggleDisabled,
  exportDisabled,
  regenerateDisabled,
  type ActionsState,
} from "../../components/cover-letters/actions";

const base: ActionsState = {
  hasSelection: true,
  regenerating: false,
  refining: false,
  exporting: false,
  hasInstructions: false,
};

describe("cover-letter actions enablement (GAP-P4-043)", () => {
  it("keeps the Request-Changes toggle clickable while a regenerate is in flight", () => {
    // The dead-control repro: a slow Regenerate leaves the panel busy, yet the
    // disclosure toggle only reveals a form and must stay interactive.
    const busy: ActionsState = { ...base, hasSelection: true, regenerating: true };
    expect(changeRequestToggleDisabled(busy)).toBe(false);
    const refining: ActionsState = { ...base, hasSelection: true, refining: true };
    expect(changeRequestToggleDisabled(refining)).toBe(false);
  });

  it("only disables the Request-Changes toggle when no letter is selected", () => {
    expect(changeRequestToggleDisabled({ hasSelection: true })).toBe(false);
    expect(changeRequestToggleDisabled({ hasSelection: false })).toBe(true);
  });

  it("gates the mutating actions on the busy state so they cannot race", () => {
    expect(regenerateDisabled({ ...base, regenerating: true })).toBe(true);
    expect(regenerateDisabled({ ...base, refining: true })).toBe(true);
    expect(regenerateDisabled({ ...base, hasSelection: false })).toBe(true);
    expect(regenerateDisabled(base)).toBe(false);
  });

  it("requires instructions and a settled state to submit a change request", () => {
    expect(changeRequestSubmitDisabled(base)).toBe(true); // no instructions
    expect(changeRequestSubmitDisabled({ ...base, hasInstructions: true })).toBe(false);
    expect(
      changeRequestSubmitDisabled({ ...base, hasInstructions: true, regenerating: true }),
    ).toBe(true);
    expect(
      changeRequestSubmitDisabled({ ...base, hasInstructions: true, refining: true }),
    ).toBe(true);
  });

  it("gates export only on selection and its own in-flight state", () => {
    expect(exportDisabled({ hasSelection: true, exporting: false })).toBe(false);
    expect(exportDisabled({ hasSelection: true, exporting: true })).toBe(true);
    expect(exportDisabled({ hasSelection: false, exporting: false })).toBe(true);
    // Independent of a background regenerate/refine (unlike the old coupling).
    expect(exportDisabled({ hasSelection: true, exporting: false })).toBe(false);
  });
});
