# Placeholder / Mock-Data Sweep (G-F) — Workstream F (2026-07-24)

## Static fingerprint grep (non-test sources)
Patterns: `lorem ipsum|placeholder|coming soon|not implemented|fake data|mock*|hardcoded`
over `apps/web/src` (excl. `__tests__`/`.test.`/`__mocks__`) and `apps/api/app`.

Triage of every hit class:
- **HTML `placeholder=` attributes** — legitimate input-field hint text, not mock data. Excluded.
- **Defensive comments/docstrings** (`base_adapter.py` "never silently ship fake
  data", `analytics.py` "never present a hardcoded guess", `llm_client.py`
  no-silent-substitution note, `offers.py` "no hardcoded" docstring,
  `cover_letters.py` `REDACTION_PLACEHOLDER` — a real sanitisation token) —
  honesty guards, not placeholders. PASS.
- **Settings → Notifications "Coming soon"** (`settings-client.tsx:840,1134`) —
  an explicit, honest disclosure: `role="status"` notice "Notification delivery
  isn't built yet — these preferences aren't functional and aren't saved",
  toggles rendered `disabled` with a "Coming soon" badge. This is the
  previously-adjudicated honest-disabled pattern (no fake success, no silent
  no-op). PASS per the launch-ready quality bar.
- `admin.py:172` "email-verification placeholder" — code comment for a real,
  persisted admin settings toggle. PASS.
- `base_adapter.py` raises `not implemented yet` for fixture-only sources —
  surfaced honestly to users via `/agents/scout/sources/availability`
  (`indeed available:false, reason: "no live discovery implementation"`). PASS.

## Production response probes (fresh)
- `GET /`, `/pricing`, `/login` HTML: 0 occurrences of `lorem ipsum|fake data|TODO`.
- Authed API data probed this run is all real user data: approvals,
  applications, jobs, `analytics/funnel` (`jobs_found:45, applied:6` — real
  DB-derived counts), 22 agent configs with honest `"model":"deterministic"`
  locks (see `retrigger-log.md`).

## Verdict
**Zero user-reachable placeholder, lorem-ipsum, mock-data, or fake-success
content found. G-F evidence: PASS.**
