# ADR-F01 — Authorization for the deployment-wide provider-credential store

- **Status:** Proposed (implemented; awaiting reviewer + qa closure)
- **Date:** 2026-08-04
- **Finding:** F-01 (BLOCKER) — `docs/delivery/PROD-UAT-2026-08-03.md`
- **Evidence:** `uat/reports/evidence/prod-uat-2026-08-03/s4-credential-scope.json`,
  `uat/reports/evidence/models-live/f01/`
- **Code:** `apps/api/app/routers/agents.py`, `apps/api/app/middleware/auth.py`,
  `apps/web/src/app/dashboard/agents/page.tsx`,
  `apps/web/src/components/agents/{api.ts,ProviderConnections.tsx,ProviderConfigModal.tsx}`

---

## 1. Context — what was actually wrong

`ProviderCredentialRepository` is a **single deployment-wide credential store**. Its
methods take a provider id and nothing else — there is no user id anywhere in the
table or the repository:

```
ProviderCredentialRepository().upsert(provider, auth_mode=…, secret=…, base_url=…)
ProviderCredentialRepository().delete(provider)
ProviderCredentialRepository().get_masked(provider)
```

Every route that reads or writes it took a plain `CurrentUser` and never consulted
`isAdmin`. `current_user` was used **only** to build the response object —
`_provider_status_object(provider, current_user["id"])` — so it was read on every
request but it never authorized anything.

The consequence: any authenticated account — including the real free-tier customer
account that exists in production right now — could

- **read** the operator's provider rows: connection `status`, credential `source`,
  the last-4 `secretHint` of the operator's real key, and `lastVerifiedAt`;
- **overwrite** the operator's credential, redirecting every LLM run on the
  deployment (including the discovery cron) to a key of their choosing;
- **delete** it, taking every agent on the deployment offline;
- **spend** the operator's money and probe their credential's validity through the
  real upstream round-trip in `POST /providers/{provider}/verify`.

qa-adversary's live probe is the decisive evidence: a non-admin `DELETE` of an
**unknown** provider returned **404**, not 401/403. The provider-name check ran
first, which proves no authorization gate was reached at all — and leaked which
provider ids exist as a side effect.

For contrast, `GET /api/admin/users` correctly returns 403 for the same account, so
a working admin gate already existed in this codebase.

### The family was larger than the initial report

Enumerating the router rather than trusting the finding table surfaced **three more**
deployment-wide routes in the same family. `app/services/anthropic_oauth.py`'s
`persist_tokens()` writes the **same** `ProviderCredential('anthropic')` row the
manual paste writes:

```python
# apps/api/app/services/anthropic_oauth.py — persist_tokens()
ProviderCredentialRepository().upsert(
    "anthropic", auth_mode="oauth_token", secret=access, base_url=None
)
```

So `POST /providers/anthropic/oauth/{start,exchange,refresh}` were ungated writes to
the deployment-wide store too. Before the gate, any customer could complete
Connect-with-Anthropic with **their own** Claude account and silently become the
credential every bare `claude-*` run on the deployment bills against. The per-user
`AnthropicOAuthState` owner check inside `/exchange` is a CSRF/state binding, not an
authorization gate — it only proves the caller started the flow they are finishing.

---

## 2. Decision — tenancy

**Admin-gate the shared store; keep the already-correct per-user store as the
customer surface.** Do **not** convert `ProviderCredential` into a per-user table.

### Why not "make it per-user"?

1. **A correct per-user store already exists and is separate.**
   `UserProviderCredential` (+ `/agents/user/providers/...`) is keyed by
   `(userId, provider)`, is encrypted the same way, and is already wired into the
   runtime through `resolve_user_credential`. Building a second one would be
   duplicate tenancy for the same concept.
2. **The deployment-wide row is load-bearing and must stay deployment-wide.**
   `resolve_credential(provider)` reads it DB-first for callers that have **no user
   context at all** — the discovery cron and the background worker. Making it
   per-user would leave those paths with no credential, i.e. a total outage, and
   would push them toward exactly the kind of silent fallback this codebase forbids.
3. **It is genuinely the operator's own property.** It is the key the operator pays
   for and meters through the plan/quota system. The right control is "only the
   operator may touch it", not "everyone gets their own copy of it".

### Why reuse `get_admin_user` rather than invent a mechanism?

`app/middleware/auth.py` already defines the gate that produces the
`{"detail":"Admin privileges required"}` 403 on `/admin/*`:

```python
def get_admin_user(current_user: CurrentUser) -> dict[str, Any]:
    if not current_user.get("isAdmin"):
        raise _ADMIN_ERROR
    return current_user

AdminUser = Annotated[dict[str, Any], Depends(get_admin_user)]
```

Swapping the annotation `CurrentUser` → `AdminUser` is the whole change per route. A
second mechanism would be a second thing to get wrong, and would answer with a
different status/detail than the rest of the product.

### Authorization before validation — for free, and deliberately

FastAPI resolves dependencies **before** entering the handler body, so the 403 is
raised before the `if provider not in _CREDENTIAL_PROVIDERS: … 404` check that used
to run first. An ungated caller now gets 403 for **every** provider id, real or
invented, and learns nothing about which ids are configured. The 404 an admin should
still see is preserved (`test_admin_unknown_provider_still_404`).

`get_admin_user` depends on `get_current_user`, so an **anonymous** caller still gets
401, never 403 — authentication continues to precede authorization.

---

## 3. Blast radius

### Routes gated (`CurrentUser` → `AdminUser`), all in `app/routers/agents.py`

| Route | Deployment-wide effect |
|---|---|
| `GET /agents/providers` | reads the shared store + server env; returns source, `secretHint`, `lastVerifiedAt` |
| `PUT /agents/providers/{provider}/credential` | overwrites the shared credential |
| `DELETE /agents/providers/{provider}/credential` | deletes the shared credential |
| `POST /agents/providers/{provider}/verify` | spends the operator's credential upstream; mutates `lastVerifyStatus` |
| `POST /agents/providers/anthropic/oauth/start` | step 1 of a flow that writes the shared row |
| `POST /agents/providers/anthropic/oauth/exchange` | **writes** the shared `anthropic` row |
| `POST /agents/providers/anthropic/oauth/refresh` | rotates the shared row / marks `needs_reauth` |

### Routes deliberately left on `CurrentUser` — and why

| Route | Reason it is not deployment-wide |
|---|---|
| `GET/PUT/DELETE/POST /agents/user/providers/...` | `UserProviderCredential`, keyed by `(userId, provider)`. This is the customer's own key surface and must stay reachable. |
| `GET /agents/providers/{provider}/models`, `POST .../models/refresh` | A model **catalog** read, not a credential. Per-user aware (`list_provider_models(provider, current_user["id"])`). Gating it would break the customer-facing "choose any model by budget" feature for every non-admin. |
| `PUT /agents/providers/{provider}` | **See §6 — open question.** Writes `AgentProvider`, whose primary key is `("userId","provider")`; every statement in the handler is scoped by `current_user["id"]`. It touches `ProviderCredential` not at all. It is the only write path behind the customer's ModelPicker. |

### Internal / server-side callers — checked, none affected

- `scripts/discovery_cron.sh` (systemd `aether-discovery.timer`) logs in as the
  **owner** (`isAdmin=true`) and calls only `POST /agents/scout/run` and
  `POST /agents/fit-scorer/run`. It never touches `/agents/providers*`. Gated either
  way, it is unaffected.
- No backend module, script or ops file makes an HTTP call to `/agents/providers*`
  (grepped across `apps/api`, `scripts`, `ops`). Server-side credential resolution
  goes through `llm_client.resolve_credential` / `resolve_user_credential`, i.e.
  **direct repository reads**, which this ADR does not touch. The worker and cron
  therefore keep working unchanged.
- Frontend callers are enumerated in `apps/web/src/components/agents/api.ts` and are
  all reached from `/dashboard/agents`, which is handled in §4.

### Operator impact

None. The owner account is `isAdmin=true` in production and retains every control:
list, save, rotate, remove, test, and the whole Connect-with-Anthropic flow.

---

## 4. What a customer sees — before vs after

**Before.** `/dashboard/agents` rendered "AI Provider Connections" to everyone. A
free-tier customer saw six cards describing the **operator's** credentials: a green
"Connected" dot, a "Saved" source badge, `Ends …7391` (the last 4 characters of the
operator's real key), the last verify timestamp, and a "Manage" button that opened a
modal wired to the deployment-wide save/remove/test endpoints. Those buttons worked.

**After.** The page resolves `isAdmin` from `/auth/me` — the same source
`components/admin/admin-guard.tsx` and `components/topbar.tsx` already use — **before
choosing which endpoint to call**. A non-admin's browser never issues the
`GET /agents/providers` request at all, so no operator row is ever transmitted; a
403-after-click would have been too late, because the panel would already have
rendered credential data and controls that can only fail.

A customer instead gets **"Your AI Provider Keys"**, built from the new
`GET /agents/user/providers/catalog`: static provider identity (name, icon, colour,
static model list — no credential material) combined with **their own**
`UserProviderCredential` rows and **their own** default-model preference. Its
"Manage" button opens the same modal in `scope="user"`, which writes
`/agents/user/providers/{id}/credential`. The Connect-with-Anthropic control is not
rendered for them, because that flow writes the deployment-wide row and is
admin-only server-side — a customer is never shown a control that can only 403.

The per-agent model pickers and the OpenRouter model catalog are unchanged for
everyone.

### Why a new endpoint rather than reusing `GET /agents/user/providers`

The existing per-user endpoint returns only the rows a user has **already stored**.
A usable panel also needs the provider identities a user *may* configure, and the
user's own default-model preference. Synthesising that list in the frontend would
duplicate `PROVIDER_SEED` in TypeScript and drift from the backend. The new endpoint
is additive, reads no deployment credential and no provider env var, and returns the
same row shape as the operator view so **one** panel component renders both.

---

## 5. Tests

New: `apps/api/tests/test_f01_provider_credential_authz.py` (24 tests) and
`apps/web/src/__tests__/agents/f01-provider-panel-scope.test.tsx` (5 tests). Both
were written before the fix and recorded failing against it — see
`uat/reports/evidence/models-live/f01/`.

Nine existing backend suites exercise the deployment-wide endpoints as the operator.
Each now overrides the shared `auth_headers` fixture with the new
`promote_user_to_admin` conftest fixture, so the fixture user **is** the operator.
No assertion in any of them was changed, relaxed or removed — only the actor, which
is the one the endpoint was always meant for. Five frontend page suites likewise pin
`fetchMe` to `isAdmin: true`; without that pin they would have silently slid onto the
customer path and stopped covering `fetchProviders` at all.

---

## 6. Open question for the orchestrator — `PUT /agents/providers/{provider}`

A second session (`apps/api/tests/test_gm2_f01_provider_route_authz.py`, GOLD-MASTER-V2
F-01) is working the same finding and has written a test asserting this route must
also return 403 for a non-admin. **This ADR takes the opposite position, and the two
tests cannot both pass.** That session's test-author flagged the same concern in
their own docstring and deferred it to the orchestrator.

The facts, which both sessions agree on:

- The handler writes `AgentProvider`, primary key `("userId","provider")`, and every
  statement is scoped by `current_user["id"]`. It never touches `ProviderCredential`.
- It is the **only** write path behind `ModelPicker.tsx` (`updateProvider` →
  `PUT /agents/providers/{id}`), the customer-facing "pick any model by budget"
  control, and its row is read back at run time as the user's provider-level default
  model (`agents.py`, the openrouter-scoped `AgentProvider` lookup).
- Its one genuine leak is informational, not a write: the response `detail` (and the
  409 message on a `status: "connected"` request) is derived from
  `_provider_env_state`, which discloses **one bit per provider** — whether the
  server has an env key for it. No secret, no hint, no timestamp.

Two defensible readings:

- **(A) Keep `CurrentUser` (this ADR's position).** It is a per-user row; gating it
  would 403 every customer's model-picker save and remove a shipped feature. Close
  the informational leak separately by not echoing `_provider_env_state`'s `detail`
  to non-admins.
- **(B) Gate it and add a replacement.** If the orchestrator wants the whole
  `/agents/providers/*` prefix operator-only for defence in depth, the gate must ship
  **together with** a per-user `PUT /agents/user/providers/{provider}` model/status
  write and a ModelPicker re-point. Gating alone trades a security hole for a live
  product regression.

Until a ruling lands, the route is unchanged and this ADR's test asserts the
current (200) behaviour for a customer.

---

## 7. Residual risk

1. **`PUT /agents/providers/{provider}` env-state disclosure** — one bit per provider
   ("does the server have an env key for X"), via `detail` and the 409 message. Not
   closed here; see §6.
2. **`GET /agents/providers/{provider}/models` falls back to the deployment key**
   when the caller has no key of their own. That is the model-choice feature's
   existing, deliberate design (it is how the catalog renders for everyone), and it
   returns a catalog, never credential material — but a customer's catalog refresh
   does consume the operator's upstream rate limit. Out of scope for F-01; flagged
   for a separate ruling.
3. **`isAdmin` is re-read per request**, so revoking admin takes effect immediately —
   but the frontend caches its `/auth/me` answer for the life of the page. A user
   de-privileged mid-session keeps the operator panel rendered until reload. The
   server gate is authoritative, so every action they attempt fails 403; only the
   already-delivered rows remain visible in that tab.
4. **`ProviderCredential` has no audit trail.** Nothing records who last wrote the
   deployment credential, so the pre-fix exposure window cannot be reconstructed from
   the database. The operator should rotate any credential that was live while the
   hole was open and treat its last-4 as disclosed.

---

# ORCHESTRATOR RULINGS — 2026-08-04T03:05Z

## Ruling 1 — `PUT /agents/providers/{provider}`: **OPTION A. Keep `CurrentUser`. Do NOT gate it.**

Two sessions wrote contradictory tests for this route: one asserts 403 for a non-admin, the other asserts 200.
They cannot both pass. **The 403 test is wrong and must be corrected**, for reasons both sessions already
agree on factually:

- the handler writes `AgentProvider`, whose PK is `("userId","provider")`;
- **every statement is scoped by `current_user["id"]`**;
- it **never touches `ProviderCredential`** — the deployment-wide store F-01 is about;
- it is the **only** write path behind the customer model picker (`ModelPicker.tsx:110` → `updateProvider`),
  read back at run time at `agents.py:1663`.

This route is therefore already correctly per-user. Gating it would 403 every customer's model-picker save —
breaking a paid feature to "fix" a route that was never part of the vulnerability. F-01 is a **tenancy** defect
about an unscoped shared store, not a rule that every `/agents/providers*` path must be admin-only; applying
the gate by URL prefix rather than by what the code actually writes would be cargo-culting the fix.

The one real residue — the echoed `_provider_env_state` `detail` (and a 409 message) disclosing **one bit per
provider**, whether the server holds an env key for it — is tracked separately. It is not a secret, hint or
timestamp, and it does not justify breaking model choice for every paying customer. Option B (gate it *paired
with* a new per-user model-preference write endpoint + a ModelPicker re-point) remains available later if that
bit is ever judged material; it is a feature change, not a security fix, and must not ride on a blocker.

**Action:** delete or correct `apps/api/tests/test_gm2_f01_provider_route_authz.py::test_non_admin_put_providers_status_model_gets_403`.
Two committed tests asserting opposite contracts for one route is a broken suite regardless of which ships.

## Ruling 2 — commit-procedure deviation: **ENDORSED. This was the right call.**

`apps/api/app/routers/agents.py` carried another session's in-flight CRITICAL-3b work. A literal
`git commit --only <path>` would have swallowed it and shipped it to main — **the exact GOV-013 failure the
rule exists to prevent**. Staging only own hunks via a validated `git apply --cached` (every retained hunk
asserted to carry an `F-01`/`AdminUser` marker, foreign hunks excluded), then verifying post-commit that HEAD
carried 7 `AdminUser` annotations and **zero** foreign markers, upheld the rule's *intent* where its letter
would have violated it.

**Standing amendment to the shared-tree rule:** `git commit --only <paths>` is the default, but when a path
you must commit ALSO carries another session's in-flight hunks, `--only` is INSUFFICIENT — stage your own
hunks explicitly and prove the foreign hunks are absent from the commit and still present in the working tree.
Disclose the deviation, as was done here.

**Correction to that agent's characterisation, for the record:** the two `# RED-PROOF-TEMP: circuit branch
disabled` markers at `:892` and `:2052` do **not** disable anything — the branch below each still executes
`raise _quota_429(...)`. They are stale, and now false, comments left over from a red proof. They carried no
behavioural risk to this deploy, but they must be removed: a comment asserting protection is disabled, sitting
above protection that is enabled, will mislead the next reader in exactly the wrong direction.

## Deploy record

API restarted 2026-08-04T02:58Z. Verified live against a real non-admin (`isAdmin=False`): **403** on
`GET /providers`, `PUT|DELETE /providers/anthropic/credential`, `POST /providers/anthropic/verify`,
`POST /providers/anthropic/oauth/start`; **401** (not 403) for anonymous; **200** on
`GET /agents/user/providers`, so the per-user store is intact. Frontend built and restarted immediately in the
same operation, per `INCIDENT-2026-07-21-web-build-clobber.md`.

**Operator action still required:** `ProviderCredential` has no audit trail, so the pre-fix exposure window
cannot be reconstructed. Rotate every provider credential that was live while the hole was open, and treat
each last-4 as disclosed.
