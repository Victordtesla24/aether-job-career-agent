// @vitest-environment jsdom
/**
 * ML-agents-cred-001 (MODELS-LIVE, BLOCKER) — frontend half of the Anthropic
 * credential normalization hardening.
 *
 * Companion to ``apps/api/tests/test_ml_cred_001.py`` (backend). The amended
 * fix (docs restated there — evidence dir under uat/reports/evidence/models-
 * live/ is gitignored) requires the pre-send trim in ``ProviderConfigModal``
 * to strip the SAME Unicode whitespace/invisibles set the backend now
 * normalizes (NBSP U+00A0, ZWSP U+200B, FEFF U+FEFF, general-punctuation
 * spaces U+2000-U+200A) plus one pair of matching surrounding quotes, not
 * just ASCII whitespace via the current bare ``secret.trim()``.
 *
 * Two things are tested:
 *
 * 1. A PURE UNIT test against an intended helper ``normalizeCredentialSecret``
 *    that ``logic.ts`` does not export today (the file already houses every
 *    other pure/testable helper for this screen — ``providerSourceBadge``,
 *    ``filterModels``, etc. — so this is the natural home for the new logic).
 *    NOTE FOR THE FIXER: if a different name/location is chosen, update the
 *    import below to match — the intent (a single pure normalize function the
 *    modal's ``save()`` calls instead of bare ``.trim()``) is what matters,
 *    not the exact identifier.
 * 2. A COMPONENT-level integration test against the actual current behaviour
 *    of ``ProviderConfigModal``'s save flow (``secret.trim()`` at line ~183):
 *    proves the value handed to ``putProviderCredential`` is NOT fully
 *    normalized today. This assertion is implementation-agnostic (it doesn't
 *    care what helper the fixer introduces) and is the stronger fail-before
 *    signal.
 *
 * This project does not install @testing-library/jest-dom, so assertions use
 * plain DOM properties / vitest matchers only (matches sibling test files).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Part 1 — pure unit test against the intended `normalizeCredentialSecret`
// helper (does not exist yet — see NOTE FOR THE FIXER above).
// ---------------------------------------------------------------------------
import * as logic from "../../components/agents/logic";

const NBSP = " ";
const ZWSP = "​";
const FEFF = "﻿";
const EM_SPACE = " ";
const API_KEY = "sk-ant-api03-FAKEtestCONSOLEkeyvalue0000000000";
const OAT01_TOKEN = "sk-ant-oat01-FAKEtestTOKENvalue0000000000deadbeef";

describe("normalizeCredentialSecret (intended pure helper, logic.ts)", () => {
  it("is exported from logic.ts", () => {
    // FAIL-BEFORE (WHY): no such export exists today — `logic.ts` has no
    // credential-normalization helper at all, so this is `undefined`.
    expect(typeof (logic as Record<string, unknown>).normalizeCredentialSecret).toBe(
      "function",
    );
  });

  it("strips NBSP / ZWSP / FEFF / general-punctuation-space wrapping", () => {
    const fn = (logic as Record<string, unknown>).normalizeCredentialSecret as (
      s: string,
    ) => string;
    // FAIL-BEFORE (WHY): `fn` is undefined (see previous test) — calling it
    // throws "fn is not a function", which is a correct failure for a helper
    // that has not been implemented yet.
    expect(fn(`${NBSP}${API_KEY}${NBSP}`)).toBe(API_KEY);
    expect(fn(`${ZWSP}${API_KEY}${ZWSP}`)).toBe(API_KEY);
    expect(fn(`${FEFF}${API_KEY}`)).toBe(API_KEY);
    expect(fn(`${EM_SPACE}${API_KEY}${EM_SPACE}`)).toBe(API_KEY);
  });

  it("strips one pair of matching surrounding quotes, including nested whitespace", () => {
    const fn = (logic as Record<string, unknown>).normalizeCredentialSecret as (
      s: string,
    ) => string;
    expect(fn(`"${API_KEY}"`)).toBe(API_KEY);
    expect(fn(`'${API_KEY}'`)).toBe(API_KEY);
    // Nested whitespace INSIDE the quote pair (paste-from-JSON case) must
    // also be cleaned up, not just the outermost edges of the raw input.
    expect(fn(`"  ${OAT01_TOKEN}  "`)).toBe(OAT01_TOKEN);
  });

  it("still behaves like plain trim for ordinary ASCII-padded input (no regression)", () => {
    const fn = (logic as Record<string, unknown>).normalizeCredentialSecret as (
      s: string,
    ) => string;
    expect(fn(`  ${API_KEY}  `)).toBe(API_KEY);
    expect(fn(API_KEY)).toBe(API_KEY);
  });
});

// ---------------------------------------------------------------------------
// Part 2 — component-level integration test: proves the CURRENT save() path
// (bare `secret.trim()`) does not fully normalize before calling the API,
// independent of whatever helper name the fixer lands on.
// ---------------------------------------------------------------------------

const putCredentialMock = vi.fn();
const deleteCredentialMock = vi.fn();
const verifyMock = vi.fn();

vi.mock("../../components/agents/api", () => ({
  putProviderCredential: (...args: unknown[]) => putCredentialMock(...args),
  deleteProviderCredential: (...args: unknown[]) => deleteCredentialMock(...args),
  verifyProvider: (...args: unknown[]) => verifyMock(...args),
}));

// eslint-disable-next-line import/first
import ProviderConfigModal from "../../components/agents/ProviderConfigModal";
// eslint-disable-next-line import/first
import type { Provider } from "../../components/agents/api";

const anthropic: Provider = {
  id: "anthropic",
  name: "Anthropic Claude",
  auth: "API Key",
  status: "unconfigured",
  model: "",
  detail: "Not configured",
  models: [],
  icon: "fa-a",
  color: "#D97757",
  source: "none",
};

afterEach(() => {
  cleanup();
  putCredentialMock.mockReset();
  deleteCredentialMock.mockReset();
  verifyMock.mockReset();
});

describe("ProviderConfigModal save() — Unicode whitespace/quote normalization (ML-agents-cred-001)", () => {
  it("strips NBSP/ZWSP/FEFF and a surrounding quote pair before PUTting the secret", async () => {
    putCredentialMock.mockResolvedValue({
      ...anthropic,
      status: "connected",
      source: "database",
      authMode: "api_key",
      secretHint: "…0000",
      detail: "API key",
    });

    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn().mockResolvedValue(undefined)}
        onNotice={vi.fn()}
      />,
    );

    // A value a user could plausibly paste from a "smart" clipboard / a
    // JSON snippet: NBSP+ZWSP+FEFF padding around a quoted API key.
    const pasted = `${FEFF}${NBSP}"${API_KEY}"${ZWSP}`;
    fireEvent.change(screen.getByTestId("provider-secret-input"), {
      target: { value: pasted },
    });
    fireEvent.click(screen.getByTestId("provider-config-save"));

    await waitFor(() => expect(putCredentialMock).toHaveBeenCalledTimes(1));
    // FAIL-BEFORE (WHY): the modal's `save()` only calls `secret.trim()`.
    // Native `String.prototype.trim()` happens to already strip the leading
    // FEFF/NBSP here (both ARE in ECMAScript's `WhiteSpace` production), but
    // it does NOT strip: (a) the trailing ZWSP (U+200B is a zero-width
    // *format* character, category Cf — NOT part of JS's whitespace set),
    // and (b) the surrounding quote pair (quotes are ordinary characters,
    // never whitespace). So the value actually sent today is still
    // `"API_KEY"` + a trailing ZWSP — quotes intact, one invisible
    // character intact — and this equality fails against the fully clean
    // expected value.
    expect(putCredentialMock).toHaveBeenCalledWith("anthropic", {
      authMode: "api_key",
      secret: API_KEY,
    });
  });
});
