# STAGE 1 — Canonical Screen-Tester Protocol (MANUAL-VERIFICATION run)

Every screen-tester follows THIS document plus its per-screen brief. Deviations = report rejected.

## Identity & inputs
You are a 3rd-party-minded manual tester on a PAID plan's behalf. You have NOT seen fix history. Inputs: (a) your wireframe file(s) under `design/screens/`; (b) your row in `uat/reports/evidence/manual-verification/screens/SCREEN-MATRIX.json` (route + endpoints + agents); (c) canonical login: `uat/reports/evidence/manual-verification/canonical-login.md` — reuse VERBATIM, production URLs only, NEVER localhost; (d) your claim rows: filter `uat/reports/evidence/manual-verification/claims/claim-ledger.json` by your screen_id; (e) baseline reference: `uat/reports/evidence/manual-verification/screens/<your-screen-or-variant>/baseline/`.

Form YOUR OWN view of what the screen SHOULD do from the wireframe + product sense BEFORE looking at what it does.

## The 9-point protocol (§3.2) — no exceptions
1. **Load & visual conformance:** navigate to the route (Playwright, production); full-page screenshot; compare against the wireframe — layout, components present, copy, empty states, loading states. Every visible deviation = finding (missing/broken/misleading components; pixel-perfection NOT required).
2. **Every interactive element:** click every button, link, tab, toggle, dropdown, menu item, pagination control, modal open/close, icon action — no exceptions. Expected vs observed for each; screenshot on anomaly. Does-nothing / throws / 404s / dead-end = finding.
3. **Every form:** submit (a) valid, (b) empty, (c) boundary/invalid (long strings, unicode, `<script>alert(1)</script>` XSS-echo check, wrong types). Honest inline validation required; no raw stack traces/5xx JSON in UI; no silent failure — a "Save" that 200s but doesn't persist = finding (reload and re-read to confirm persistence).
4. **UI↔backend wiring:** network capture on; every action fires the expected endpoint from the matrix; response shape drives the UI (no ignored errors, no optimistic success on failed calls); data round-trips (create→appears; edit→persists after reload; delete→gone after reload).
5. **AI-agent integration (if your matrix row lists agents):** actually RUN them from the UI. Verify real generation (vs fixture fingerprints — grep the test suite `apps/api/tests/fixtures/` for reusable fingerprint strings and assert their ABSENCE in output), honest progress/error states, quota decrement visible where applicable, audit fields populated (API read), output quality sane for a paying user. Hangs / silent failure / generic filler = finding. If a paywall (402) blocks the run, record it precisely (endpoint, response, UI behavior) — it is claim-relevant evidence, and escalate as UNSURE-PAYWALL so the orchestrator can adjudicate entitlement for deep agent testing.
6. **Error & edge states:** unauthenticated access to the route (clean redirect/401 required); a forced backend error where feasible; slow-network behavior (throttled reload); browser back/forward through the flow.
7. **Console/log hygiene:** zero uncaught console errors, zero failed requests not surfaced to the user, zero server 5xx during your session. Record ALL console events (a log-tailer captures server side; your session window timestamps must be precise UTC).
8. **Claim verification:** for each of your claim-ledger rows, reproduce the claimed behavior live → verdict CONFIRMED / REFUTED / PARTIALLY-TRUE / UNVERIFIABLE-FROM-UI with evidence paths. Never adjudicate from documents.
9. **VERIFY TWICE:** reproduce every finding a second time in a FRESH browser session before filing. Non-reproducible-once = FLAKY with both transcripts. UNSURE about anything → file an UNSURE item (screenshots + both candidate interpretations); NEVER guess.

## Shared-environment rules (concurrent testers on one prod account)
- Prefix ALL data you create with `MV-<your-screen-id>-` (job notes, stories, letters, contacts, etc.). Only assert on YOUR prefixed data in list views — other testers run concurrently.
- NEVER delete/modify data you did not create. NEVER change account-level settings (password, email, plan) unless your brief explicitly assigns it; if your screen requires it (settings), change ONLY fields your brief lists, record before-values, and restore them.
- Do not test "concurrent tab" scenarios against another tester's flows — use your own two tabs.

## Findings — schema (§4.1)
One JSON row per finding; ids `MV-<screen>-<seq>` (seq from 001, per screen):
```json
{"id":"MV-<screen>-001","screen":"<screen-id>","severity":"BLOCKER|HIGH|MEDIUM|LOW","category":"defect|wiring|agent-integration|visual|validation|security|performance|claim-refuted|coverage-gap","summary":"","reproduction":["exact numbered human steps"],"expected":"","observed":"","evidence":["relative artifact paths"],"claimRefs":["CLM-xxx"],"status":"OPEN","owner":null,"fixCommits":[],"verifiedBy":null}
```
Severity: BLOCKER = data loss / payment-quota wrong / security exposure / core journey broken / fabricated content. HIGH = broken or misleading with workaround. MEDIUM = degraded UX, inconsistent state, noisy errors. LOW = cosmetic.

## Outputs (ALL mandatory — a report missing any section is rejected)
Write under `uat/reports/evidence/manual-verification/screens/<screen-id>/`:
- `TESTING-OUTCOME-REPORT.md`: screen id/name/route/wireframe ref; environment + commit SHA + UTC timestamps (session start/end); ELEMENT INVENTORY (every control found → tested → result); FINDINGS table (schema above); CLAIM VERDICTS (one row per claim); UNSURE items; SCREENSHOTS INDEX; console/network/server-log summaries; explicit NOT-TESTED list (HUMAN-GATED reasons only — "ran out of ideas" is not acceptable); tester sign-off line with your agent role+model.
- `findings.json`: array of your finding rows (exact schema).
- `test-artifacts/` — screenshots (numbered, referenced from the report), network captures, any scripts you wrote.
Do NOT write to `docs/delivery/MANUAL-VERIFICATION-GAPS.json` — the orchestrator is its sole writer.

## Prohibitions
Production only (never localhost); no code changes; no service restarts; no `git` writes; no fixture/mock injection; no self-closure of findings; no skipping a control because it "probably works"; no secrets in artifacts (first 8 chars max).
