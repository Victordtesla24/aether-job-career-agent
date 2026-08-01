# ADR-CALENDAR-V4 — Google Calendar: scope expansion, incremental authorization, and the supersession of ADR-AG-1's "no calendar" restriction

- **Status**: Accepted (implemented)
- **Date**: 2026-08-01
- **Workstream**: GOLD-MASTER V4 §10 / W-CAL
- **Supersedes (in part)**: ADR-AG-1 — "Draft time-proposal reply text on interview-stage
  threads; no calendar read/write claimed"
- **Related**: ADR-PC-1 (PKCE code_verifier in OAuth state), GM2-EMAIL-001 (connection status
  must reflect real token validity), ADR-TR-1 (lazy idempotent DDL)

---

## 1. Context

Google OAuth already worked in production with three Gmail scopes plus the three
identity scopes. `https://www.googleapis.com/auth/calendar.events` was **absent** from
`GOOGLE_SCOPES` (`apps/api/app/services/google_oauth.py`), so the product held no
calendar capability at all.

ADR-AG-1 (wave-4C) therefore forbade the Scheduling Agent from claiming any calendar
behaviour, and the agent's module docstring, its system prompt, its result object
(`calendarIntegration: bool = False`, described as "always False"), its user-facing
messages and its catalog card all asserted "Aether reads and writes NO calendar". That
was the correct call at the time: without a scope, any availability the agent produced
would have been invented, and the codebase's core promise is that it never fabricates.

GOLD-MASTER V4 §1.3 records that this restriction was **architectural, not permanent**:
it holds only while no real Calendar OAuth exists, and W-CAL supersedes it once one does.

## 2. Decision

### 2.1 ADR-AG-1's "no calendar" clause is superseded — conditionally, not wholesale

`calendar.events` is now requested, so the capability is real. But it is real **per
account**, because Google's granular consent screen lets a user grant Gmail and decline
Calendar. The restriction is therefore replaced by a *condition that is checked on every
run*, not by a blanket new claim:

- `SchedulingResult.calendarIntegration` is `True` only when that run genuinely read the
  user's calendar; it remains `False` otherwise.
- `SchedulingResult.calendarStatus` reports which of `connected` / `not_connected` /
  `scope_missing` / `needs_reauth` / `unavailable` applied, every run, including on the
  early-return refusal paths.
- The agent's system prompt is assembled per run: a calendar-connected run gets a clause
  saying the availability came from the user's real free/busy; an unconnected run keeps
  the original "you have NO access to this candidate's calendar" clause verbatim.
- The catalog card states both branches rather than picking one.

Everything ADR-AG-1 said about *not booking* and *not sending* is untouched and still
holds: the Scheduling Agent still writes nothing and sends nothing. Interview **events**
are written by the Interview Center, on an explicit user action, not by an agent.

### 2.2 Incremental authorization is load-bearing and must not be removed

`build_consent_url` already passed `include_granted_scopes=true`. That flag is what makes
this change safe: adding a scope to an OAuth client does **not** retroactively grant it to
tokens issued earlier, and without incremental authorization Google would issue a token
carrying only the newly-consented scopes — silently destroying every existing Gmail grant
at the next reconnect. With it, Google *adds* `calendar.events` to the account's existing
authorization and returns a token covering both. The flag is now documented in
`build_consent_url`'s docstring as a do-not-remove invariant, and pinned by
`test_consent_url_requests_calendar_with_incremental_authorization`.

### 2.3 Persist the scopes Google GRANTED, never the scopes we REQUESTED

`google-auth` exposes two different things and they are not the same:

| attribute | meaning |
|---|---|
| `credentials.scopes` | the list we **requested** (copied verbatim off the OAuth session) |
| `credentials.granted_scopes` | parsed from the token response's own `scope` field — what the user really agreed to |

`exchange_code` previously persisted `" ".join(creds.scopes or GOOGLE_SCOPES)`. Left
unchanged, adding `calendar.events` to `GOOGLE_SCOPES` would have recorded a Calendar
grant for **every** user, including those who declined it — and every downstream
"Calendar connected" check would then have repeated that fabrication. It now persists
`granted_scope_string(creds)`, which prefers `granted_scopes`.

### 2.4 Relax oauthlib's scope-equality check — for the duration of one exchange only

`oauthlib.oauth2.rfc6749.parameters.validate_token_parameters` **raises** when the granted
scope set differs from the requested set, unless `OAUTHLIB_RELAX_TOKEN_SCOPE` is set. Two
things make that difference the normal case after this change:

1. `include_granted_scopes=true` makes Google return previously-granted scopes this
   request never asked for;
2. granular consent lets the grant be a strict subset of the request.

Measured, with the relaxation disabled (adversarial self-check, 2026-08-01):

```
Token exchange failed: Scope has changed from
"…/gmail.labels …/calendar.events …/gmail.modify openid …/userinfo.email …/userinfo.profile …/gmail.send"
to
"…/gmail.labels …/gmail.modify openid …/userinfo.email …/userinfo.profile …/gmail.send".
```

That is a user who ticked Gmail and unticked Calendar — and the exchange blows up, so
they lose **Gmail** too. `_relaxed_token_scope()` is a context manager around
`flow.fetch_token` only: it records the previous value, sets the flag, and restores it in
a `finally`, serialized by a module-level lock so two concurrent callbacks cannot
interleave set/restore. It is pinned by
`test_relax_env_flag_is_not_left_set_after_exchange`.

**This relaxes a protocol pedantry, not an honesty guard.** The scopes we store still come
from `granted_scopes`, and every calendar feature gates on that stored truth.

### 2.5 Three distinct, separately-reported refusals — never one vague failure

`app/services/calendar_service.py` raises:

- `CalendarNotConnectedError` — no Google account linked at all;
- `CalendarScopeNotGrantedError` — account linked (Gmail works), `calendar.events` absent
  from the **granted** scopes;
- `CalendarAuthError` — the grant existed and expired or was revoked.

They are separate because the user's next action is different in each case, and because
folding "you chose not to grant this" into "authentication failed" is misleading.
Transient network trouble maps to the plain `CalendarError`, never to a "reconnect"
instruction the user cannot act on usefully.

### 2.6 An interview is recorded even when the calendar write is refused

`POST /interviews` creates the row first, then attempts the calendar write, then reports
the outcome in a `calendar` block on the response:

```
{"status": "created"|"not_connected"|"scope_missing"|"needs_reauth"|"failed",
 "event_id": <Google's id or null>, "html_link": <Google's link or null>, "message": <actionable>}
```

Rationale: the interview record is what the user asked for, and a user who never connected
Google must still be able to track interviews. `status: "created"` is emitted **only** when
Google returned a real event id — a response that omits the id is reported as `failed`,
not as success. The outcome is also persisted on the row itself (§2.7) so the answer to
"is this on my calendar?" survives the next page load.

### 2.7 Additive, idempotent DDL only

`InterviewSchedule` gains `calendarEventId`, `calendarHtmlLink`, `calendarSyncStatus` and
`calendarSyncedAt` via `ADD COLUMN IF NOT EXISTS` under a transaction-scoped advisory lock
(id `7420240719`), per ADR-TR-1. Nothing is dropped, renamed or retyped; the previous
release never selects these columns and keeps working against the migrated table.

### 2.8 Calendar status is LIVE-probed, per GM2-EMAIL-001

GM2-EMAIL-001 established that a connection status must reflect real token validity, not
merely the presence of a stored row. `connection_status()` therefore:

- returns `not_connected` with **no** network call when there is no Google account;
- returns `scope_missing` with **no** network call when the stored *granted* scopes settle
  it (probing would be pointless and would cost a round-trip);
- otherwise issues one real `calendarList.list(maxResults=1)` call and reports
  `connected` / `needs_reauth` / `unavailable` from what Google actually said.

`unavailable` exists precisely so that "we could not check" is never rounded up to
"connected".

### 2.9 The no-invented-availability rail is not weakened

`unsupported_time_expressions` (the rail that withholds a draft mentioning a weekday or
clock time the evidence does not support) is untouched. Calendar-derived windows are added
to the **evidence corpus**, exactly like the caller's own supplied windows, because they
are read facts rather than model output. To keep the rail from false-positiving on mere
formatting, each window's label deliberately carries several renderings of the same real
fact:

```
Tuesday 5 August, morning — 10:00 AM to 11:00 AM (10am to 11am), Australia/Sydney
```

The timezone is the calendar's **own** `timeZone` (read from `calendars.get('primary')`),
not a guess. Windows are business-hours, weekdays only, within the next 14 days, and every
one of them is checked against the real free/busy response before being proposed.

## 3. Alternatives considered

| Alternative | Why rejected |
|---|---|
| Separate OAuth client / separate consent flow for Calendar | A second refresh token per user, a second revoke path, and a second thing to keep in sync with Gmail. Incremental authorization on the existing client achieves the same result with one grant. |
| Fail `POST /interviews` outright when Calendar is not connected | Regresses every existing user: interviews could no longer be tracked without a Google account. The calendar is an addition to the record, not a precondition for it. |
| Keep persisting requested scopes and detect the grant by trial API call | Costs a network call on every check and reports a capability we were told, in writing, was declined. `granted_scopes` is the authoritative answer and is already in the token response. |
| Set `OAUTHLIB_RELAX_TOKEN_SCOPE` process-wide at import | Changes global oauthlib behaviour for anything else in the process, forever, from a side effect of an import. Scoped context manager keeps the blast radius to one exchange. |
| Derive availability from business hours alone when free/busy is unreadable | That is invented availability — precisely what this agent exists to prevent. An unreadable calendar degrades to "ask the sender for windows". |

## 4. Consequences

**Positive**

- Interview events land on the user's real calendar, with the role, company, time and a
  link back to the job posting.
- The Scheduling Agent proposes windows the user is genuinely free, instead of asking the
  other side to propose everything.
- Calendar connection state is truthful everywhere it is shown, including the case where
  Gmail works and Calendar does not.

**Costs / risks accepted**

- Existing users must reconnect Google once to grant the new scope. Until they do, Gmail
  keeps working unchanged and every calendar surface reports `scope_missing` with an
  actionable message. Nothing silently degrades.
- The settings endpoint makes one extra Google API call for users whose stored grant
  includes `calendar.events`. Bounded to one call, fully exception-guarded, and never able
  to 500 the settings page.
- `OAUTHLIB_RELAX_TOKEN_SCOPE` is briefly set process-wide during a token exchange. The
  window is a single HTTP call, lock-serialized and restored in a `finally`; the worst case
  of an overlap is that a concurrent exchange is also relaxed, which is the desired
  behaviour anyway.

## 5. Enforcement

`apps/api/tests/test_wcal_google_calendar.py` (23 tests) pins: the scope list, incremental
authorization, granted-vs-requested scope persistence, the partial-grant survival path,
the relax flag not leaking, all three honest refusals, the event payload shape, the
interview-creation contract in all three connection states, free/busy windows never
overlapping a busy block, a revoked grant surfacing as `needs_reauth` rather than a vague
`unavailable`, and the three settings statuses including the live probe.
`apps/web/src/app/dashboard/settings/__tests__/W-CAL-calendar-status.test.tsx` pins that
the Connected Accounts badge renders the real status and never falls back to green.
