# Incomplete Features & TODOs — Aether Job & Career Agent
**Generated:** 2026-07-30  
**Scope:** Non-test source code (`apps/web/src`, `apps/api/app`, `packages/*/src`)  
**Patterns:** TODO, FIXME, PLACEHOLDER, NotImplementedError, hardcoded, stub, mock, unavailable, etc.

---

## Summary

- **Total grep hits:** 432
- **User-reachable findings:** 143 (33%)
- **Documentation/fixture refs (not user-reachable):** 289

### Breakdown by Category

| Category | Count | User-Reachable |
|----------|-------|----------------|
| TODO/FIXME | 0 | 0 |
| NotImplementedError (benign) | 10 | 5 |
| Hardcoded values | 25 | 25 |
| Placeholder/Stub/Mock/Dummy | 113 | 113 |
| Documentation/Fixtures only | 284 | 0 |

---

## NotImplementedError Stubs (Benign)

**Count:** 10  
**Note:** These are intentional benign skips (e.g., optional job sources with no live mode).  
**User-Reachable:** 5

- `apps/api/app/agents/scout_agent.py:13`  
  > source that genuinely has no live mode (``NotImplementedError`` — the legacy

- `apps/api/app/agents/scout_agent.py:67`  
  > except NotImplementedError as exc:

- `apps/api/app/services/discovery/base_adapter.py:25`  
  > Distinct from :class:`NotImplementedError`, which means the source has *no

- `apps/api/app/services/discovery/base_adapter.py:27`  
  > differently: a ``NotImplementedError`` is a benign skip, while an

- `apps/api/app/services/discovery/base_adapter.py:103`  
  > raise NotImplementedError(

- `apps/api/app/services/discovery/adapter_registry.py:114`  
  > ``BaseAdapter._fetch_live``'s ``NotImplementedError`` stub unmodified)

- `apps/api/app/services/discovery/adzuna_adapter.py:10`  
  > ``NotImplementedError`` so the scout records the source as a benign ``skipped``

- `apps/api/app/services/discovery/adzuna_adapter.py:64`  
  > raise NotImplementedError(

- `apps/api/app/services/discovery/seek_adapter.py:302`  
  > credentials remain a ``NotImplementedError`` (no live mode available).

- `apps/api/app/services/discovery/seek_adapter.py:307`  
  > raise NotImplementedError(

## Hardcoded Values

**Count:** 25  
**User-Reachable:** 25

- `apps/web/src/app/dashboard/page.tsx:9`  
  > * REQ-TM-10 — nothing is hardcoded (funnel is data-driven per audit D11).

- `apps/api/app/services/llm_client.py:2029`  
  > from the hardcoded fallback the user never picked. The un-chosen

- `apps/api/app/services/gmail_service.py:281`  
  > hardcoded 0. It is nullable and stays NULL until a thread is actually triaged

- `apps/api/app/routers/offers.py:10`  
  > their Jobs) with the user's persisted manual offers. There are no hardcoded

- `apps/api/app/routers/cover_letters.py:775`  
  > # banned generic opener the studio previously hardcoded (D-0021, GAP-P4-049).

- `apps/api/app/routers/analytics.py:207`  
  > #: You must never present a hardcoded guess as if it were sourced market

- `apps/api/app/routers/analytics.py:695`  
  > Previously this fabricated a comparison against hardcoded constants

- `apps/api/app/routers/agents.py:339`  
  > #: catalog rather than hardcoded (F-3, PROD-VERIFY-5A).

- `apps/api/app/routers/agents.py:378`  
  > # No hardcoded seed models: OpenRouter's model list is the LIVE catalog

- `apps/api/app/routers/agents.py:473`  
  > # GAP-PC-005 fix: the old string hardcoded "standby (Anthropic is the

- `apps/api/app/routers/agents.py:1045`  
  > # the previous hardcoded zero that hid real spend from the audit row,

- `apps/api/app/routers/agents.py:1541`  
  > scout runs targeted at the *user's* real goals rather than a hardcoded

- `apps/api/app/routers/agents.py:2045`  
  > distinct implemented agent, pipeline nodes first (F-3). It was a hardcoded

- `apps/api/app/routers/agents.py:2829`  
  > #: would be exactly the hardcoded-allowlist antipattern §3.1.3 forbids.

- `apps/api/app/routers/agents.py:2845`  
  > hardcoded model allowlist.

... and 10 more (see JSON for full list)

## Placeholder / Stub / Mock / Dummy References

**Count:** 113  
**User-Reachable:** 113

Sample (first 10 user-reachable):

- `apps/web/src/app/dashboard/agents/page.tsx:15`  
  > * Every control is wired to a real endpoint — nothing is mock. The full

- `apps/web/src/app/dashboard/agents/page.tsx:149`  
  > // timestamp on initial load instead of a "not yet refreshed" placeholder.

- `apps/api/app/services/fabrication_guard.py:277`  
  > """Object wrapper so agents can dependency-inject / mock the guard."""

- `apps/api/app/services/stripe_gateway.py:1`  
  > """Thin Stripe SDK wrapper (ADR-P6-STRIPE-MOCK).

- `apps/api/app/services/stripe_gateway.py:56`  
  > """Read a field from a Stripe object (dict-like) or a mock dict."""

- `apps/api/app/services/resume_tailor.py:1104`  
  > intended proposed planned

- `apps/api/app/agents/interview_prep_agent.py:1`  
  > """Interview Prep Agent — STAR+R mock Q&A grounded in the user's OWN data (wave-4B).

- `apps/api/app/agents/interview_prep_agent.py:3`  
  > HONEST SCOPE (ADR-AG-1). This is the best-grounded of the twelve planned cards:

- `apps/api/app/agents/interview_prep_agent.py:7`  
  > in STAR + Reflection form. There is no interactive mock-interview session, no

- `apps/api/app/agents/interview_prep_agent.py:9`  
  > "realistic mock interviews" is corrected in the same change.

... and 103 more (see JSON for full list)

## Documentation / Fixture References Only

**Count:** 284  
**Note:** These are fixture/test-mode documentation, not user-reachable features.
**Examples:** fixture mode docs, live/replay mode explanations, test helper comments.

---

## Files with Findings (File-by-File)

### apps/api/app/agents/compliance_agent.py (3 total, 0 user-reachable)

**documentation_only:** 3

⚪ Line 44: "flagged", "cover_letter_id", "coverLetterUnavailable",
⚪ Line 45: "cover_letter_unavailable",
⚪ Line 189: output.get("coverLetterUnavailable") or output.get("cover_letter_unavailable")

### apps/api/app/agents/cover_letter_agent.py (23 total, 4 user-reachable)

**documentation_only:** 19

⚪ Line 32: LLMUnavailableError,
⚪ Line 107: #: article "the" (MV-cover-letter-studio-003 reopened bypass #2) would
⚪ Line 152: # (MV-cover-letter-studio-003 reopened bypass #1: "weave the word PINEAPPLE
⚪ Line 208: #: the article "the" (MV-cover-letter-studio-003 reopened bypass #2). The
⚪ Line 276: token that would gut the letter (MV-cover-letter-studio-003 bypass #2)."""
... and 14 more

**placeholder:** 4

🔴 Line 242: #: Placeholder a redacted injection clause is replaced with. Exposed so callers
🔴 Line 244: #: placeholder words rather than surface them as "keywords".
🔴 Line 245: REDACTION_PLACEHOLDER = "[instruction-like content removed]"
🔴 Line 266: out.append(f" {REDACTION_PLACEHOLDER} ")

### apps/api/app/agents/email_agent.py (4 total, 0 user-reachable)

**documentation_only:** 4

⚪ Line 246: raise EmailAgentError("triage model unavailable") from exc
⚪ Line 340: pass  # keep the first draft; flagged is surfaced honestly below
⚪ Line 351: self, prompt: str, corpus: str, fixture_key: str
⚪ Line 359: fixture_key=fixture_key,

### apps/api/app/agents/interview_prep_agent.py (5 total, 4 user-reachable)

**documentation_only:** 1

⚪ Line 48: * an LLM failure → propagated ``LLMUnavailableError`` → the standard honest 503

**placeholder:** 4

🔴 Line 1: """Interview Prep Agent — STAR+R mock Q&A grounded in the user's OWN data (wave-4B).
🔴 Line 3: HONEST SCOPE (ADR-AG-1). This is the best-grounded of the twelve planned cards:
🔴 Line 7: in STAR + Reflection form. There is no interactive mock-interview session, no
🔴 Line 9: "realistic mock interviews" is corrected in the same change.

### apps/api/app/agents/outreach_support.py (2 total, 0 user-reachable)

**documentation_only:** 2

⚪ Line 281: fixture_key: str = "default",
⚪ Line 304: fixture_key=fixture_key,

### apps/api/app/agents/recruiter_outreach_agent.py (1 total, 1 user-reachable)

**placeholder:** 1

🔴 Line 3: HONEST SCOPE (ADR-AG-1). The card's old tip said "Planned: first-touch outbound to

### apps/api/app/agents/scheduling_agent.py (1 total, 0 user-reachable)

**documentation_only:** 1

⚪ Line 326: fixture_key="proposed" if result.proposedTimes else "default",

### apps/api/app/agents/scout_agent.py (4 total, 1 user-reachable)

**documentation_only:** 2

⚪ Line 14: fixture-only LinkedIn/Indeed adapters) is a benign ``skipped``.
⚪ Line 68: # Source has no live mode at all (legacy fixture-only) — a

**not_implemented_error:** 2

⚪ Line 13: source that genuinely has no live mode (``NotImplementedError`` — the legacy
🔴 Line 67: except NotImplementedError as exc:

### apps/api/app/main.py (10 total, 0 user-reachable)

**documentation_only:** 10

⚪ Line 99: fixture responses instead of real model output with no visible error
⚪ Line 124: ``AETHER_DISCOVERY_FIXTURE_DIR`` is a test/dev env var that redirects
⚪ Line 129: serve stale fixture data as if it were live job listings, with no
⚪ Line 134: Non-production deployments with the fixture dir set print a warning
⚪ Line 137: fixture_dir = os.environ.get("AETHER_DISCOVERY_FIXTURE_DIR", "").strip()
... and 5 more

### apps/api/app/repositories/job.py (5 total, 0 user-reachable)

**documentation_only:** 5

⚪ Line 64: # Deliberately NOT implemented by importing ``app.workers.board_sweep`` — do
⚪ Line 94: #: honest ``coverLetterUnavailable`` degrade flag (either spelling).
⚪ Line 98: AND ({run}."output"->'coverLetterUnavailable' = 'true'::jsonb
⚪ Line 99: OR {run}."output"->'cover_letter_unavailable' = 'true'::jsonb)))
⚪ Line 150: middle of a larger SELECT whose own ``%s`` placeholders are positionally

### apps/api/app/routers/admin.py (1 total, 1 user-reachable)

**placeholder:** 1

🔴 Line 172: # Settings (signup toggle + email-verification placeholder)

### apps/api/app/routers/agents.py (75 total, 17 user-reachable)

**documentation_only:** 58

⚪ Line 47: LLM_UNAVAILABLE_USER_MESSAGE,
⚪ Line 48: LLMUnavailableError,
⚪ Line 359: #: with no ``backend`` are roadmap cards ("planned") and are deliberately absent:
⚪ Line 941: # below. ``None`` when replay/fixture mode served the run (no
⚪ Line 993: except LLMUnavailableError as exc:
... and 53 more

**hardcoded:** 9

🔴 Line 339: #: catalog rather than hardcoded (F-3, PROD-VERIFY-5A).
🔴 Line 378: # No hardcoded seed models: OpenRouter's model list is the LIVE catalog
🔴 Line 473: # GAP-PC-005 fix: the old string hardcoded "standby (Anthropic is the
🔴 Line 1045: # the previous hardcoded zero that hid real spend from the audit row,
🔴 Line 1541: scout runs targeted at the *user's* real goals rather than a hardcoded
... and 4 more

**placeholder:** 8

🔴 Line 211: # ADR-AG-1 (wave-4B): "realistic mock interviews" described an interactive
🔴 Line 1450: False for planned agents (no backend) and deterministic backends
🔴 Line 2716: for non-LLM agents, "—" for planned ones).
🔴 Line 2722: active = paused = error = planned = 0
🔴 Line 2731: state = "planned"
... and 3 more

### apps/api/app/routers/analytics.py (2 total, 2 user-reachable)

**hardcoded:** 2

🔴 Line 207: #: You must never present a hardcoded guess as if it were sourced market
🔴 Line 695: Previously this fabricated a comparison against hardcoded constants

### apps/api/app/routers/billing.py (7 total, 1 user-reachable)

**documentation_only:** 6

⚪ Line 7: ``app.services.stripe_gateway`` (mocked in unit tests, ADR-P6-STRIPE-MOCK).
⚪ Line 150: status.HTTP_503_SERVICE_UNAVAILABLE,
⚪ Line 224: status.HTTP_503_SERVICE_UNAVAILABLE,
⚪ Line 298: pass  # hook point for a reminder notification; no state change
⚪ Line 815: status.HTTP_503_SERVICE_UNAVAILABLE,
... and 1 more

**placeholder:** 1

🔴 Line 148: # Honest 503 — never a fabricated checkout URL (ADR-P6-STRIPE-MOCK).

### apps/api/app/routers/cover_letters.py (12 total, 4 user-reachable)

**documentation_only:** 8

⚪ Line 51: LLM_UNAVAILABLE_USER_MESSAGE,
⚪ Line 53: LLMUnavailableError,
⚪ Line 743: def _draft(prompt: str, fixture_key: str) -> tuple[str, list[str], list[str]]:
⚪ Line 750: fixture_key=fixture_key,
⚪ Line 821: except LLMUnavailableError:
... and 3 more

**hardcoded:** 1

🔴 Line 775: # banned generic opener the studio previously hardcoded (D-0021, GAP-P4-049).

**placeholder:** 3

🔴 Line 26: REDACTION_PLACEHOLDER,
🔴 Line 431: redaction placeholder is removed; each token is stripped of edge punctuation
🔴 Line 437: sanitized = (sanitize_untrusted_text(jd) or "").replace(REDACTION_PLACEHOLDER, " ")

### apps/api/app/routers/emails.py (2 total, 0 user-reachable)

**documentation_only:** 2

⚪ Line 130: status.HTTP_503_SERVICE_UNAVAILABLE,
⚪ Line 136: raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

### apps/api/app/routers/google_oauth.py (2 total, 0 user-reachable)

**documentation_only:** 2

⚪ Line 56: status.HTTP_503_SERVICE_UNAVAILABLE,
⚪ Line 62: raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

### apps/api/app/routers/jobs.py (4 total, 1 user-reachable)

**documentation_only:** 3

⚪ Line 38: A filter on an unknown or currently-unavailable source must never return
⚪ Line 43: by a known-but-unavailable source.
⚪ Line 61: f"Source '{source}' is currently unavailable: {row['reason']}. "

**placeholder:** 1

🔴 Line 8: real resume + posting (no mock, no randomness)

### apps/api/app/routers/offers.py (2 total, 1 user-reachable)

**documentation_only:** 1

⚪ Line 11: fixture offers.

**hardcoded:** 1

🔴 Line 10: their Jobs) with the user's persisted manual offers. There are no hardcoded

### apps/api/app/routers/workspaces.py (4 total, 3 user-reachable)

**documentation_only:** 1

⚪ Line 76: #    run — the honest 503 when the LLM is unavailable, whose row

**hardcoded:** 1

🔴 Line 4: All five endpoints serve **real data from the database**.  No hardcoded

**placeholder:** 2

🔴 Line 622: # single not-connected placeholder so the UI can prompt the first connect.
🔴 Line 801: Replaces the old client-only "Add Offer" mock: the offer is now written to

### apps/api/app/services/career_data.py (2 total, 0 user-reachable)

**documentation_only:** 2

⚪ Line 272: fixture = fetch(username) if fetch is not None else None
⚪ Line 273: profile = scrape_github_profile(username, fixture=fixture)

### apps/api/app/services/credential_vault.py (1 total, 0 user-reachable)

**documentation_only:** 1

⚪ Line 49: f"{KEY_ENV} is not configured — credential encryption is unavailable. "

### apps/api/app/services/discovery/adapter_registry.py (8 total, 0 user-reachable)

**documentation_only:** 7

⚪ Line 7: fixture tests and the explicit ``AETHER_ENABLE_SEEK`` opt-in can still
⚪ Line 55: # Legacy fixture-only sources (no live mode; skipped in production).
⚪ Line 91: adapter) so fixture tests and the opt-in path can still instantiate it.
⚪ Line 113: - legacy fixture-only adapters (LinkedIn/Indeed — they inherit
⚪ Line 115: are honestly unavailable with a "no live" reason. They stay in
... and 2 more

**not_implemented_error:** 1

⚪ Line 114: ``BaseAdapter._fetch_live``'s ``NotImplementedError`` stub unmodified)

### apps/api/app/services/discovery/adzuna_adapter.py (3 total, 1 user-reachable)

**documentation_only:** 1

⚪ Line 8: (``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY``) — never hardcoded. When the credentials

**not_implemented_error:** 2

⚪ Line 10: ``NotImplementedError`` so the scout records the source as a benign ``skipped``
🔴 Line 64: raise NotImplementedError(

### apps/api/app/services/discovery/base_adapter.py (15 total, 3 user-reachable)

**documentation_only:** 11

⚪ Line 6: - **fixture mode** (``fixture=`` dict passed in, or loaded from
⚪ Line 7: ``AETHER_DISCOVERY_FIXTURE_DIR``): parse a recorded payload — used in tests
⚪ Line 26: live mode at all* (a legacy fixture-only source). The scout treats the two
⚪ Line 40: records this as a disclosed ``status="blocked"`` (calm "unavailable" pill),
⚪ Line 73: def __init__(self, fixture: dict[str, Any] | None = None) -> None:
... and 6 more

**not_implemented_error:** 3

🔴 Line 25: Distinct from :class:`NotImplementedError`, which means the source has *no
⚪ Line 27: differently: a ``NotImplementedError`` is a benign skip, while an
🔴 Line 103: raise NotImplementedError(

**placeholder:** 1

🔴 Line 104: f"Live HTTP discovery for '{self.source}' is not implemented yet; "

### apps/api/app/services/discovery/live_http.py (2 total, 0 user-reachable)

**documentation_only:** 2

⚪ Line 7: Tests must NEVER hit this module — adapters run in fixture mode under
⚪ Line 8: pytest (``AETHER_DISCOVERY_FIXTURE_DIR`` is set by conftest).

### apps/api/app/services/discovery/seek_adapter.py (3 total, 1 user-reachable)

**documentation_only:** 1

⚪ Line 375: ``sourceUrl``) and the Seek API fixture shape (``advertiser``/

**not_implemented_error:** 2

⚪ Line 302: credentials remain a ``NotImplementedError`` (no live mode available).
🔴 Line 307: raise NotImplementedError(

### apps/api/app/services/discovery/wellfound_adapter.py (1 total, 0 user-reachable)

**documentation_only:** 1

⚪ Line 40: message = f"Wellfound public listings unavailable: {exc}"

### apps/api/app/services/fabrication_guard.py (1 total, 1 user-reachable)

**placeholder:** 1

🔴 Line 277: """Object wrapper so agents can dependency-inject / mock the guard."""

### apps/api/app/services/gmail_service.py (2 total, 1 user-reachable)

**documentation_only:** 1

⚪ Line 414: "Gmail email service is temporarily unavailable — server "

**hardcoded:** 1

🔴 Line 281: hardcoded 0. It is nullable and stays NULL until a thread is actually triaged

### apps/api/app/services/llm_client.py (60 total, 1 user-reachable)

**documentation_only:** 59

⚪ Line 4: - ``replay`` (default): read a canned response from the fixture directory —
⚪ Line 6: - ``record``: call the live endpoint and persist the response as a fixture.
⚪ Line 8: - ``auto``: try the live endpoint first (recording the fixture on success);
⚪ Line 11: raise an honest :class:`LLMUnavailableError` (mapped to HTTP 503 by the
⚪ Line 12: routers — never an unhandled 500). It NEVER serves a recorded fixture as if
... and 54 more

**hardcoded:** 1

🔴 Line 2029: from the hardcoded fallback the user never picked. The un-chosen

### apps/api/app/services/portfolio_scraper.py (5 total, 0 user-reachable)

**documentation_only:** 5

⚪ Line 8: * **Fixture mode** (`fixture=` provided) — deterministic, offline, used by tests.
⚪ Line 9: * **Live mode** (`fixture=None`) — fetches from the public GitHub REST API using
⚪ Line 75: fixture: Optional[dict[str, Any]] = None,
⚪ Line 79: Pass ``fixture`` (a ``{"profile": {...}, "repos": [...]}`` dict) to run
⚪ Line 85: data = fixture if fixture is not None else _fetch_live(username)

### apps/api/app/services/resume_tailor.py (4 total, 1 user-reachable)

**documentation_only:** 3

⚪ Line 2299: is never shipped, and no fixture is ever served as if it were the verdict
⚪ Line 2317: "entailment verifier unavailable; conservatively reverting %d changed "
⚪ Line 2346: than serving a fixture), so the caller reverts conservatively.

**placeholder:** 1

🔴 Line 1104: intended proposed planned

### apps/api/app/services/stripe_gateway.py (3 total, 2 user-reachable)

**documentation_only:** 1

⚪ Line 21: """Raised when a required Stripe secret (or the SDK) is unavailable."""

**placeholder:** 2

🔴 Line 1: """Thin Stripe SDK wrapper (ADR-P6-STRIPE-MOCK).
🔴 Line 56: """Read a field from a Stripe object (dict-like) or a mock dict."""

### apps/api/app/workers/board_sweep.py (16 total, 0 user-reachable)

**documentation_only:** 16

⚪ Line 46: #: Consecutive LLM-unavailable failures that abort the stretch (systemic
⚪ Line 246: #: ``status='completed'`` with ``output.coverLetterUnavailable = true``
⚪ Line 251: #: ``CoverLetterResult.cover_letter_unavailable`` dataclass field that
⚪ Line 252: #: ``asdict()`` surfaces for the LLM-unavailable-on-first-draft degrade
⚪ Line 269: AND ({run}."output"->'coverLetterUnavailable' = 'true'::jsonb
... and 11 more

### apps/api/app/workers/tasks.py (9 total, 0 user-reachable)

**documentation_only:** 9

⚪ Line 15: - NEVER fixture content on failure — ``mark_failed`` writes an honest error
⚪ Line 44: """An honest, secret-free failure string. Never fixture content.
⚪ Line 47: deliberately chose (e.g. the honest LLM-unavailable message of
⚪ Line 273: # with an honest ``coverLetterUnavailable`` result instead of a raw
⚪ Line 281: "coverLetterUnavailable": True,
... and 4 more

### apps/web/src/app/admin/settings/page.tsx (1 total, 1 user-reachable)

**placeholder:** 1

🔴 Line 9: * placeholder, surfaced only to signal the roadmap item.

### apps/web/src/app/admin/users/page.tsx (2 total, 2 user-reachable)

**placeholder:** 2

🔴 Line 71: placeholder="email or name"
🔴 Line 72: className="mt-1 w-56 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text

### apps/web/src/app/dashboard/agents/page.tsx (4 total, 2 user-reachable)

**documentation_only:** 2

⚪ Line 515: // "Unavailable" treatment the dashboard feed already
⚪ Line 517: <span className="text-aether-muted">Unavailable</span>

**placeholder:** 2

🔴 Line 15: * Every control is wired to a real endpoint — nothing is mock. The full
🔴 Line 149: // timestamp on initial load instead of a "not yet refreshed" placeholder.

### apps/web/src/app/dashboard/cover-letters/page.tsx (3 total, 0 user-reachable)

**documentation_only:** 3

⚪ Line 122: *  - a guard rejection or a first-draft LLM-unavailable degrade carries
⚪ Line 123: *    `coverLetterUnavailable: true` (ML-cover-002/003) — the async job now
⚪ Line 133: if (result.missingResume || result.coverLetterUnavailable || !result.cover_letter_id) {

### apps/web/src/app/dashboard/email/page.tsx (7 total, 7 user-reachable)

**placeholder:** 7

🔴 Line 40: // placeholder — NOT the red "low score" style — so a not-yet-analyzed thread
🔴 Line 1090: placeholder="recipient@example.com"
🔴 Line 1092: className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-whit
🔴 Line 1104: placeholder="Email subject"
🔴 Line 1106: className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-whit
... and 2 more

### apps/web/src/app/dashboard/interviews/page.tsx (4 total, 4 user-reachable)

**placeholder:** 4

🔴 Line 14: * scheduled" placeholder over a fully-working backend and there was no UI
🔴 Line 585: placeholder="e.g. Level 4, 55 Collins St — or leave blank"
🔴 Line 598: placeholder="https://…"
🔴 Line 636: placeholder="Predicted questions, stories to tell, things to research…"

### apps/web/src/app/dashboard/jobs/page.tsx (12 total, 6 user-reachable)

**documentation_only:** 6

⚪ Line 450: // than showing a fabricated "(unavailable)" label; filtering a dead source
⚪ Line 473: const isSourceUnavailable = useCallback(
⚪ Line 731: {lastSync ? `Last synced: ${timeAgo(lastSync)}` : "Sync time unavailable"}
⚪ Line 784: <p className="text-[11px] text-aether-muted-dim">Sync status unavailable — run Sync Now to
⚪ Line 850: disabled={isSourceUnavailable(s)}
... and 1 more

**hardcoded:** 1

🔴 Line 448: // authority on which sources are live-filterable — never hardcoded here.

**placeholder:** 5

🔴 Line 6: * Live wiring (no mock data):
🔴 Line 834: placeholder="Role…"
🔴 Line 837: className="glass w-32 rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs p
🔴 Line 862: placeholder="Location…"
🔴 Line 865: className="glass w-32 rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs p

### apps/web/src/app/dashboard/networking/lib.ts (2 total, 1 user-reachable)

**documentation_only:** 1

⚪ Line 8: * empty-board check — can be unit-tested against a contacts fixture without

**placeholder:** 1

🔴 Line 43: * empty state rather than a fake placeholder.

### apps/web/src/app/dashboard/page.tsx (1 total, 1 user-reachable)

**hardcoded:** 1

🔴 Line 9: * REQ-TM-10 — nothing is hardcoded (funnel is data-driven per audit D11).

### apps/web/src/app/dashboard/resume/page.tsx (1 total, 1 user-reachable)

**hardcoded:** 1

🔴 Line 44: *  hardcoded third party (MV-adv-resume-studio-006). */

### apps/web/src/app/dashboard/settings/settings-client.tsx (9 total, 6 user-reachable)

**documentation_only:** 3

⚪ Line 384: // there — the render falls back to an honest "Price unavailable" rather
⚪ Line 923: data-testid="notifications-unavailable-notice"
⚪ Line 1049: : "Price unavailable"}

**placeholder:** 6

🔴 Line 149: // deployment, never a placeholder.
🔴 Line 774: placeholder="e.g. octocat"
🔴 Line 797: placeholder="https://your-portfolio.example"
🔴 Line 823: placeholder="Paste the text from your LinkedIn ‘About’ / summary section…"
🔴 Line 928: aren&rsquo;t saved by &ldquo;Save Changes&rdquo;. Coming soon.
... and 1 more

### apps/web/src/app/login/page.tsx (2 total, 2 user-reachable)

**placeholder:** 2

🔴 Line 114: className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:te
🔴 Line 128: className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:te

### apps/web/src/app/signup/page.tsx (3 total, 3 user-reachable)

**placeholder:** 3

🔴 Line 126: className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:te
🔴 Line 141: className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:te
🔴 Line 161: className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:te

### apps/web/src/components/agents/AgentConfigGrid.tsx (9 total, 9 user-reachable)

**placeholder:** 9

🔴 Line 42: planned: "bg-white/25",
🔴 Line 49: planned: "text-aether-muted-dim",
🔴 Line 56: planned: "border-white/5 opacity-75",
🔴 Line 63: planned: "Planned",
🔴 Line 143: {agent.status === "planned" ? null : (
... and 4 more

### apps/web/src/components/agents/AgentModelPicker.tsx (3 total, 3 user-reachable)

**placeholder:** 3

🔴 Line 5: * non-planned agent card so a user can choose ANY model from the live catalog
🔴 Line 172: placeholder="Search models…"
🔴 Line 173: className="min-w-0 flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11p

### apps/web/src/components/agents/AgentStats.tsx (1 total, 1 user-reachable)

**hardcoded:** 1

🔴 Line 5: * derived from real AgentRun history via GET /agents/stats — no hardcoded

### apps/web/src/components/agents/ModelPicker.tsx (3 total, 3 user-reachable)

**hardcoded:** 1

🔴 Line 12: *    derived from the fetched catalog at click-time — never a hardcoded id.

**placeholder:** 2

🔴 Line 221: placeholder="Search 300+ models by name or id…"
🔴 Line 222: className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-whit

### apps/web/src/components/agents/Orchestration.tsx (3 total, 0 user-reachable)

**documentation_only:** 3

⚪ Line 63: // "Unavailable" badge already applies to this exact run shape.
⚪ Line 115: ? { key: r.id, label: `${r.agentName} · unavailable`, progress: 100, active: false, degrad
⚪ Line 313: ? `${run.agentName} unavailable (degraded)`

### apps/web/src/components/agents/ProviderConfigModal.tsx (6 total, 6 user-reachable)

**placeholder:** 6

🔴 Line 38: placeholder: string;
🔴 Line 52: placeholder: "sk-ant-api…",
🔴 Line 58: placeholder: "sk-ant-oat01-…",
🔴 Line 67: placeholder: "Paste API key",
🔴 Line 490: placeholder="code#state"
... and 1 more

### apps/web/src/components/agents/api.ts (5 total, 4 user-reachable)

**documentation_only:** 1

⚪ Line 97: // test fixture) that predates the freshness contract still parses cleanly.

**placeholder:** 4

🔴 Line 21: status: z.enum(["active", "paused", "error", "planned"]),
🔴 Line 40: planned: z.number().optional(),
🔴 Line 165: // back to the literal "deterministic" for non-LLM/planned agents, the same
🔴 Line 235: * initial load, not a "not yet refreshed" placeholder. Same honest-error

### apps/web/src/components/agents/logic.ts (3 total, 3 user-reachable)

**hardcoded:** 1

🔴 Line 163: * click-time (never a hardcoded id that might not exist):

**placeholder:** 2

🔴 Line 60: status: "active" | "paused" | "error" | "planned",
🔴 Line 62: return { active: "Active", paused: "Paused", error: "Error", planned: "Planned" }[status];

### apps/web/src/components/analytics/MarketPulse.tsx (1 total, 0 user-reachable)

**documentation_only:** 1

⚪ Line 303: <p className="text-xs font-semibold text-amber-300">External market benchmark unavailable<

### apps/web/src/components/cover-letters/ActionsPanel.tsx (2 total, 2 user-reachable)

**placeholder:** 2

🔴 Line 122: placeholder="e.g. Lead with the AI/ML delivery experience and keep it under 250 words."
🔴 Line 123: className="w-full rounded-lg border border-white/10 bg-transparent px-3 py-2 text-xs text-

### apps/web/src/components/dashboard/feed.ts (7 total, 1 user-reachable)

**documentation_only:** 6

⚪ Line 54: * every honest degrade path (LLM unavailable on first draft, fabrication/
⚪ Line 57: * which mark the run `completed` with `output.coverLetterUnavailable = true`
⚪ Line 69: return out.coverLetterUnavailable === true;
⚪ Line 83: return { label: "Unavailable", cls: "bg-white/8 text-aether-muted border-white/10" };
⚪ Line 182: // QA-RES-F: the writing model was unavailable / the fabrication
... and 1 more

**placeholder:** 1

🔴 Line 202: return { text: "planned the discovery → tailoring pipeline", highlight: null, metric: null

### apps/web/src/components/dashboard/sourceStatus.ts (2 total, 0 user-reachable)

**documentation_only:** 2

⚪ Line 36: // a calm neutral "unavailable" pill, never a red error re-alarming on
⚪ Line 45: ? "unavailable (blocked by source)"

### apps/web/src/components/offers/AddOfferModal.tsx (9 total, 9 user-reachable)

**placeholder:** 9

🔴 Line 142: opts: { required?: boolean; placeholder?: string; ref?: boolean } = {},
🔴 Line 163: placeholder={opts.placeholder}
🔴 Line 166: className={`min-h-[44px] w-full rounded-lg border bg-black/25 py-2.5 text-sm text-white pl
🔴 Line 210: {field("company", "Company", { required: true, placeholder: "e.g. Figma", ref: true })}
🔴 Line 211: {field("role", "Role", { placeholder: "e.g. Senior TPM" })}
... and 4 more

### apps/web/src/components/sidebar.tsx (3 total, 0 user-reachable)

**documentation_only:** 3

⚪ Line 22: // undefined = loading, null = unavailable, otherwise live counts
⚪ Line 122: <p className="text-[11px] text-aether-muted-dim">Plan unavailable</p>
⚪ Line 162: ? "Agent status unavailable"

### apps/web/src/components/stories/story-form.tsx (4 total, 4 user-reachable)

**placeholder:** 4

🔴 Line 24: "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placehol
🔴 Line 73: placeholder="Title — e.g. Reduced ATO test automation effort by 92%"
🔴 Line 96: placeholder={label}
🔴 Line 112: placeholder="Tags (comma separated) — e.g. Leadership, Delivery"

### apps/web/src/components/topbar.tsx (2 total, 2 user-reachable)

**placeholder:** 2

🔴 Line 255: placeholder="Search jobs, applications, agents…"
🔴 Line 270: className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm p

### apps/web/src/lib/agents-feedback.ts (4 total, 2 user-reachable)

**documentation_only:** 2

⚪ Line 88: if (response.coverLetterUnavailable) {
⚪ Line 215: * unavailable"}`); this pulls the JSON `detail` string out when present and

**hardcoded:** 2

🔴 Line 239: * the hardcoded copy below was built for). That plain, non-JSON message is
🔴 Line 297: // NF-final-closure-002: this hardcoded "run Scout to discover jobs" copy

### apps/web/src/lib/api/client.ts (1 total, 1 user-reachable)

**hardcoded:** 1

🔴 Line 9: *   prefill (GAP-P4-068 removed the unused, hardcoded DEMO_CREDENTIALS

### apps/web/src/lib/api/coverLetters.ts (2 total, 0 user-reachable)

**documentation_only:** 2

⚪ Line 40: // unavailable on the first draft. The async job now COMPLETES with this shape
⚪ Line 43: coverLetterUnavailable?: boolean;

### apps/web/src/lib/api/workspaces.ts (2 total, 1 user-reachable)

**documentation_only:** 1

⚪ Line 14: * optional here only so existing fixture literals without it still type-check. */

**placeholder:** 1

🔴 Line 374: * replacing the old client-only mock). */

### apps/web/src/lib/auth/next-auth-options.ts (1 total, 1 user-reachable)

**placeholder:** 1

🔴 Line 19: // Placeholder dependencies until the persistence layer is wired in Phase 2.

### apps/web/src/lib/config/legal.ts (3 total, 3 user-reachable)

**placeholder:** 3

🔴 Line 13: *     name) when unset: a truthful generic, never a bracket placeholder or an
🔴 Line 17: *     published rather than showing a placeholder.
🔴 Line 40: * value that isn't exactly 11 digits (e.g. a placeholder or malformed

### apps/web/src/lib/navigation.ts (1 total, 1 user-reachable)

**placeholder:** 1

🔴 Line 49: * pathname, and by the graceful placeholder shown for dashboard sections whose
