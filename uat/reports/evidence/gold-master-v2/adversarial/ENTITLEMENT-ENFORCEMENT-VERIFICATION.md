# ENTITLEMENT ENFORCEMENT VERIFICATION — server-side vs UI-only

**Adversarial verifier:** qa-adversary (independent; did not author, fix, or first-test any of this)
**Production target:** https://5cb5f0620.abacusai.cloud
**Repo @ commit:** `c569abe`
**Run window (UTC):** 2026-07-31T00:53:12Z → 2026-07-31T00:58:02Z
**Identity:** `gm2-nonadmin-1785454990@example.com` — non-admin, plan `free`, status `active`
(per `uat/reports/evidence/gold-master-v2/phase0/CANONICAL-NONADMIN-LOGIN.md`)
**Method:** direct `curl` against the production REST API with the Free account's bearer token,
browser bypassed entirely. No source, `.env`, or subscription row was modified.
**Mission:** try hard to REFUTE the claim that entitlement is enforced only in the browser.

---

## 1. Executive verdict

| Reported defect | Verdict |
|---|---|
| `GM2-STORY-009` — Story Bank UI-paywalled while "the underlying REST API is ungated" | **CONFIRMED as a fact, REFUTED as a security/revenue bypass.** The API is genuinely ungated (201/204 for a Free account), but Story Bank consumes **zero** paid LLM capacity. The real defect is monetisation inconsistency, not capacity theft. |
| `ML-JOBS-003` / `ML-RESUME-003` — part (a): the agent REST API is ungated | **REFUTED.** Every agent-run endpoint hard-blocks with 402 server-side, and the gate fires *before* resource lookup. Enforcement is real. |
| `ML-JOBS-003` / `ML-RESUME-003` — part (b): Free tier advertised 5 runs but gets 402 at 0/5 used | **CONFIRMED, and materially worse than reported.** This is not stale frontend copy — the **backend's own API** tells the user `runsAllowed: 5, runsUsed: 0` and advertises "5 tailored agent runs / month", while the gate grants zero. |
| **NEW — `ADV-ENT-001`** (found by this review, not previously reported) | **CONFIRMED server-side enforcement bypass:** `POST /cover-letters/{id}/refine` makes a live REASONING-tier LLM call with **no** entitlement gate, **no** quota reserve, **no** spend cap and **no** `AgentRun` audit row. |

**Overall `server_side_bypass`: PARTIAL.** The agent pipeline — the product's main paid surface — is
correctly and honestly walled server-side. One real ungated paid-LLM route exists, and it is reachable
by **lapsed/cancelled subscribers**, not by a fresh Free account.

**No paid LLM capacity was consumed by this review.**

---

## 2. Endpoint-by-endpoint probe table (verbatim statuses)

All probes: production, Free account bearer token, `curl`, no browser. Statuses are verbatim.

### 2.1 Read paths

| # | Method | Endpoint | Status | Body excerpt | UI behaviour | Gated? |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/auth/me` | **200** | `{"id":"c56667cb…","isAdmin":false}` | n/a | n/a |
| 2 | GET | `/api/billing/subscription` | **200** | `quota: {runsUsed:0, runsAllowed:5, spendCapUsd:1.0}` | visible | exempt by design |
| 3 | GET | `/api/billing/plans` | **200** | free `runsPerMonth: 5` | visible | public |
| 4 | GET | `/api/billing/entitlement` | **200** | `{"active_paid":false,"requiresSubscription":true}` | drives UI wall | exempt by design |
| 5 | GET | `/api/stories` | **200** | `[]` | **full-screen paywall** | **NO** |
| 6 | GET | `/api/stories/stats` | **200** | `{"total":0,…}` | **full-screen paywall** | **NO** |
| 7 | GET | `/api/jobs` | **200** | `[]` | **full-screen paywall** | **NO** |
| 8 | GET | `/api/resumes` | **200** | `[]` | **full-screen paywall** | **NO** |
| 9 | GET | `/api/cover-letters` | **200** | `[]` | **full-screen paywall** | **NO** |
| 10 | GET | `/api/applications` | **200** | `[]` | **full-screen paywall** | **NO** |
| 11 | GET | `/api/agents/catalog` | **200** | catalog JSON | paywall | NO |
| 12 | GET | `/api/agents/runs` | **200** | `[]` | paywall | NO |
| 13 | GET | `/api/analytics/overview` | **404** | `{"detail":"Not Found"}` | — | route does not exist |

*Read paths return only the caller's **own** rows (all empty for this fresh account) — no cross-user leak
was observed. These are the user's own data, so "ungated" here is defensible; see §5.*

### 2.2 Agent-run paths — the paid surface

Probed twice: first with an empty body (validation fires first), then with a **valid** body so the
request actually reaches the entitlement gate.

| # | Method | Endpoint | Body | Status | Body excerpt |
|---|---|---|---|---|---|
| 14 | POST | `/api/agents/scout/run` | `{}` | 422 | `Field required: query, location` |
| 15 | POST | `/api/agents/scout/run` | `{"query":"data engineer","location":"Sydney"}` | **402** | `{"error":"subscription_required",…,"upgradeUrl":"/pricing"}` |
| 16 | POST | `/api/agents/tailor/run` | `{"job_id":"nonexistent-job-id-adv"}` | **402** | `subscription_required` |
| 17 | POST | `/api/agents/cover-letter/run` | `{"job_id":"nonexistent-job-id-adv"}` | **402** | `subscription_required` |
| 18 | POST | `/api/agents/fit-scorer/run` | `{"job_id":"nonexistent-job-id-adv"}` | **402** | `subscription_required` |
| 19 | POST | `/api/agents/story-extractor/run` | `{}` | **402** | `subscription_required` |
| 20 | POST | `/api/agents/email/run` | `{}` | **402** | `subscription_required` |
| 21 | POST | `/api/agents/pipeline/run` | `{}` | **402** | `subscription_required` |
| 22 | POST | `/api/agents/matcher/run` | `{}` | **402** | `subscription_required` |
| 23 | POST | `/api/agents/board-sweep/trigger` | `{}` | 202 | `{"status":"skipped","reason":"no board work or deduped"}` — no work, no LLM |
| 24 | POST | `/api/agents/test-run` | `{"agent_key":"coverLetter"}` | 200 | cost **preview** only; never invokes the LLM (`agents.py:3838-3841`) |

**Decisive observation (refutes "the API is ungated"):** probes 16–18 pass a **non-existent** `job_id`
and still return **402**, not 404. The entitlement gate therefore executes **before** any resource
lookup — it is a true precondition, not a cosmetic error mapped from a failed lookup.

### 2.3 Write paths

| # | Method | Endpoint | Status | Result |
|---|---|---|---|---|
| 25 | POST | `/api/stories` | **201** | **Row created.** `id: c74af947836a209d9d98b9eba`, persisted and readable |
| 26 | GET | `/api/stories` (after 25) | 200 | 1 row returned; `/stories/stats` → `{"total":1,…}` — **write was real** |
| 27 | DELETE | `/api/stories/c74af947836a209d9d98b9eba` | **204** | Deleted; `GET /api/stories` → `[]` (state restored) |
| 28 | POST | `/api/resumes` | 422 | `Field required: label` — validation only; gate never reached |
| 29 | POST | `/api/cover-letters/bogus-adv-id/refine` | **404** | `{"detail":"Cover letter not found"}` — **NOT 402** |

**Probe 29 is the decisive differential.** On every gated route (16–18) a bogus id yields **402**
because the gate runs first. On `/refine`, a bogus id yields **404** — the handler proceeds straight to
resource lookup because **there is no gate on that route at all**.

---

## 3. Server-side guard map (file:line)

### 3.1 The gate itself — real, and correctly placed

| Component | Location | Behaviour |
|---|---|---|
| Flag reader | `apps/api/app/repositories/billing.py:331-345` `subscription_gate_enabled()` | Reads `AETHER_REQUIRE_PAID_SUBSCRIPTION` from `os.environ` on **every call**; default **ON**. OFF only for `{false,0,no,off}` (`billing.py:328` `_GATE_OFF`). |
| Entitlement predicate | `apps/api/app/repositories/billing.py:428-450` `has_active_paid_subscription()` | True **iff** `status ∈ (active, trialing, past_due)` **AND** `planId <> 'free'`. |
| The gate | `apps/api/app/routers/agents.py:723-757` `_require_active_subscription()` | Raises 402 `subscription_required` with `upgradeUrl: /pricing`. |
| Sync enforcement point | `apps/api/app/routers/agents.py:798-800` (`_record_run`, first statement) | Gate runs **before** the audit row, quota reserve, and any LLM call. |
| Async enforcement point | `apps/api/app/routers/agents.py:1884` (`_execute_reserved_run`) | Same gate on the worker/enqueue seam. |
| Pipeline enforcement point | `apps/api/app/routers/agents.py:1945` | Same gate for `/agents/pipeline/run`. |
| Scoped system exemption | `apps/api/app/routers/agents.py:700-720` `_is_system_run()` | Requires the `X-Aether-System-Run` secret, constant-time compared; **ignored entirely when the secret is unset** — no bypass-by-omission. Scoped to `_SYSTEM_RUN_EXEMPT_AGENTS`. |

**Assessment:** this is a competent, honest, server-side implementation. Gate-before-work ordering,
fail-closed flag default, constant-time secret compare, and both sync and async seams covered.
`[VERIFIED — file:line + probes 15-22]`

### 3.2 GUARDED endpoints (verified 402 server-side)

`/agents/scout/run`, `/agents/tailor/run`, `/agents/cover-letter/run`, `/agents/fit-scorer/run`,
`/agents/story-extractor/run`, `/agents/email/run`, `/agents/pipeline/run`, `/agents/{name}/run`
(generic route → `_dispatch` → `_record_run`, `agents.py:3917`), `/resumes/upload` (dispatches
`storyExtractor`, `resumes.py:115`, and the 402 is deliberately re-raised at `:118-121`).

### 3.3 UNGATED endpoints

| Endpoint | Consumes paid LLM? | Evidence |
|---|---|---|
| `GET/POST/PUT/DELETE /stories*` (`stories.py:137,143,158,163,173`) | **No** — pure CRUD; file contains zero LLM imports | probes 5,6,25,27 |
| `GET /jobs`, `/resumes`, `/cover-letters`, `/applications` | **No** — reads of the caller's own rows | probes 7-10 |
| `GET /resumes/{id}/ats` (`resumes.py:136`) | **No** — docstring and code are **deterministic** ATS scoring, no LLM | `[VERIFIED file:line]` |
| **`POST /cover-letters/{id}/refine`** (`cover_letters.py:653`) | **YES** | §4 below |

**Exhaustiveness check:** across the whole API, LLM invocation sites outside `app/agents/` are exactly
two —
`app/services/resume_tailor.py:2081,2132,2370` (reachable **only** via `tailor_agent.py:26`, which is
gated) and `app/routers/cover_letters.py:743-749` (ungated).
`[VERIFIED — grep of `LLMClient()|.complete_json(` over `app/`, excluding `app/agents/` and `llm_client.py`]`

---

## 4. `ADV-ENT-001` — CONFIRMED ungated paid-LLM endpoint

**Endpoint:** `POST /api/cover-letters/{letter_id}/refine` — `apps/api/app/routers/cover_letters.py:653-656`

**The LLM call** (`cover_letters.py:743-750`):

```python
    llm = LLMClient()

    def _draft(prompt: str, fixture_key: str) -> tuple[str, list[str], list[str]]:
        raw = llm.complete_json(
            "cover_letter_refine",
            _REFINE_SYSTEM_PROMPT,
            prompt,
            model=get_model("REASONING"),
```

This is a live call on the **REASONING** tier — the expensive tier, not the Free plan's `light` tier.

**Absence of any guard — `[VERIFIED file:line]`:**
`grep -c "subscription\|_record_run\|_require_active\|quota" apps/api/app/routers/cover_letters.py` → **0**.
The router is registered with no dependencies (`app/main.py:300`,
`app.include_router(cover_letters.router, prefix="/cover-letters", …)`), and `cover_letters.py:66` is a
bare `APIRouter()`. There is no middleware gate (`main.py` has exactly one `add_middleware` at `:272`,
and it is not an entitlement check).

**Live differential confirmation — `[VERIFIED probe 29, 2026-07-31T00:55:54Z]`:**
`POST /api/cover-letters/bogus-adv-id/refine` → **404 "Cover letter not found"**, whereas
`POST /api/agents/tailor/run` with an equally bogus id → **402**. The route reaches resource lookup
with no entitlement evaluation.

**What is bypassed:** because `/refine` never enters `_record_run`, it skips *all four* controls at
once — the entitlement gate, the atomic plan-quota reserve, the monthly spend cap, and the `AgentRun`
audit row. The spend is therefore **unmetered and unaudited**: it appears in no quota counter and no
billing-provenance record.

**Exploitability — the honest boundary.** Reaching the LLM requires (a) a `CoverLetter` row owned by
the caller and (b) non-empty resume text (`cover_letters.py:667-673` → 422 otherwise). The **only**
producer of an original `CoverLetter` row is the gated `cover_letter_agent`
(`app/agents/cover_letter_agent.py:23,1139`); `/refine`'s own `CoverLetterRepository().create`
(`cover_letters.py:845`) requires a pre-existing letter. Therefore:

- A **fresh Free account cannot** reach this LLM call — it has no letters. `[VERIFIED probe 9: `/cover-letters` → `[]`]`
- A **lapsed / cancelled / unpaid ex-subscriber CAN.** `has_active_paid_subscription`
  (`billing.py:428-450`) flips to false on `canceled`/`unpaid`, and the webhook downgrades the plan to
  `free` — but **nothing deletes their cover letters**. Every letter accumulated while paying remains a
  permanent, unmetered handle on REASONING-tier capacity. `[INFERRED — code path; not probed, because
  proving it live would require manipulating a real subscription row, which is out of scope]`

This is the answer to task item 6: **the bypass is specifically a lapsed-subscriber bypass.** The
economic shape is "cancel your subscription, keep refining cover letters forever."

---

## 5. `GM2-STORY-009` — confirmed as fact, refuted as a capacity bypass

`POST /stories` returned **201** and the row was genuinely persisted and re-readable
(`stats.total` went 0 → 1). `DELETE` returned **204**. The Story Bank REST surface is completely
ungated. `[VERIFIED probes 25-27, 2026-07-31T00:55:54Z–00:58:02Z]`

**But the screen-tester's implied severity is wrong in one direction and right in another:**

- **Wrong:** no paid LLM capacity is reachable here. `stories.py` has no LLM import; the enrichment
  (`category`, `impact`) is derived arithmetically from the row (`stories.py:26-49,130-134`). A Free
  user calling `POST /stories` costs the business nothing. This is **not** a revenue-theft bypass.
- **Right, for a different reason the testers did not identify:** the server's **own plan catalog sells
  "Cover letters + story bank" as a Starter-tier (paid) feature** — verbatim from
  `GET /api/billing/plans`. A paid-tier feature with zero server-side enforcement is a monetisation
  gap regardless of its LLM cost. `[VERIFIED probe 3]`

Simultaneously the UI **over-blocks**: `SubscriptionGate` is applied at the whole dashboard shell
(`apps/web/src/app/dashboard/layout.tsx`), so it hides the user's **own data** behind a paywall. Note
that this over-gating is **deliberate and already escalated**, not accidental —
`apps/web/src/components/subscription-gate.tsx:24-28` states the "open the whole dashboard to free
users" decision is escalated to the product owner as ADR-MV-02 D1 / H-4. The UI gate is otherwise
well-built: it fails **closed** on entitlement-fetch error (`subscription-gate.tsx:14-19`), so it is not
bypassable by forcing the entitlement call to error.

---

## 6. Pricing vs. actual server entitlement — CONFIRMED mismatch

The reported framing ("`/pricing` is stale marketing copy") is **too generous**. `/pricing` is not
hardcoded: `apps/web/src/app/pricing/page.tsx:379` renders `{plan.runsPerMonth} agent runs / month`
straight from the live `GET /billing/plans` response. **The backend is the source of the claim.**

Three server-side artefacts contradict the server's own gate:

| Server artefact | Says | Reality under the gate |
|---|---|---|
| `GET /api/billing/plans` → free `features` | `"5 tailored agent runs / month"`, `"Resume tailoring + ATS scoring"` | 0 runs; tailoring 402s |
| `GET /api/billing/subscription` → `quota` | `runsAllowed: 5, runsUsed: 0, spendCapUsd: 1.0` | 0 usable runs |
| `RATIFIED_PLANS` (`billing.py:43`) | `("free", "Free", 0, None, 5, "light", 1.00, 0)` — 5 runs, US$1 cap | never consumable while the gate is ON |

The provisioning code actively creates the contradiction: `ensure_user_billing`
(`billing.py:288-310`) inserts a `UsageQuota` row with `runsAllowed = 5` for every new user, which the
gate then makes unusable. The product **provisions a freemium tier it refuses to honour**, and reports
that unusable balance back to the user through its own API.

This is a **misleading representation about an entitlement**, made by the server, to a customer, on a
product transacting in real AUD — the consumer-law exposure the brief flags. It is corroborated
independently by the pre-existing `ADR-MV-02` (`docs/delivery/ADR-MV-02-paywall-marketing.md:10-15`),
which already names these as "two internally-conflicting ratified signals" and defers the business
decision — so this has been known and unresolved, not newly introduced.

**`pricing_matches_server_entitlement`: false.**

---

## 7. `AETHER_REQUIRE_PAID_SUBSCRIPTION` — effect

- **Definition:** `apps/api/app/repositories/billing.py:331-345`. Read from `os.environ` on every call
  (hot-reloadable, never baked into source). Default `"true"`; disabled only by
  `{false, 0, no, off}` (case-insensitive, `billing.py:328`).
- **Effective production behaviour: ENFORCED (ON).** Not read from the `.env` file — established
  behaviourally, which is stronger: probes 15–22 returned 402 for a `free`-plan user, which is only
  reachable when `subscription_gate_enabled()` is True. `[VERIFIED probes 15-22]` No raw value is
  reported here.
- **Does it explain the 402?** **Yes, completely.** The 402 is correct, intended behaviour of a
  deliberate "limited beta is subscription-only" policy — not a bug, and not a UI artefact. The defect
  is not the 402; it is that the plan catalog, the quota provisioner and `/pricing` were never
  reconciled with that policy.
- **Fail-safe posture:** correct. Unsetting the variable leaves the gate **ON**. There is no
  bypass-by-omission.

---

## 8. Answers to the brief's decisive questions

**3. Can the Free account successfully invoke any endpoint that consumes paid LLM capacity, or that the
UI refuses to show it?**

- Paid LLM capacity: **No, not with a fresh Free account.** Every LLM-bearing route reachable from a
  zero-state Free account returned 402. `paid_capacity_consumed_by_free_account: false`.
- Endpoints the UI refuses to show: **Yes, extensively** — `/stories` (read *and* write, 201/204),
  `/jobs`, `/resumes`, `/cover-letters`, `/applications`, `/agents/catalog`, `/agents/runs` all
  returned 200 while the UI renders a full-screen paywall. These expose only the caller's own data.
- The one genuine paid-capacity bypass (`/cover-letters/{id}/refine`) is real but requires a
  pre-existing letter, making it a **lapsed-subscriber** bypass.

**4. Inverse check — is the UI refusing something the user is genuinely entitled to?** **Yes.** The
server grants the Free account `runsAllowed: 5` and advertises 5 runs plus "Resume tailoring + ATS
scoring", then denies all of it. Both the UI *and* the API refuse an advertised entitlement.

---

## 9. Severity recommendations

| ID | Finding | Severity | Justification |
|---|---|---|---|
| **ADV-ENT-001** | `POST /cover-letters/{id}/refine` — ungated, unmetered, unaudited REASONING-tier LLM call | **HIGH** | Direct margin leak: a cancelled subscriber retains permanent access to the most expensive model tier. Bypasses the spend cap *and* the `AgentRun` audit trail, so the spend is invisible to billing reconciliation and to the admin spend view. Mitigating factor (why not CRITICAL): not reachable by an anonymous or fresh Free user; requires a prior paid relationship. **Fix:** call `_require_active_subscription` / route through `_record_run` at `cover_letters.py:653`. |
| **ADV-ENT-002** | Server advertises a Free entitlement (5 runs, tailoring, ATS) it universally denies | **HIGH** | Not stale copy — the backend API itself makes the representation to the customer, and reports a fabricated usable balance (`runsUsed: 0 / runsAllowed: 5`). Australian Consumer Law exposure on a product taking real AUD. Already flagged in ADR-MV-02 and still unresolved. **Fix is a one-line business decision**, then reconcile `RATIFIED_PLANS`, `ensure_user_billing`, and the plan `features` strings. |
| **ADV-ENT-003** | Story Bank sold as a Starter feature but 100% unenforced server-side | **MEDIUM** | Paid-tier feature given away; zero LLM cost, so the loss is positional not financial. Compounded by the UI hiding the user's own data. |
| **ADV-ENT-004** | `POST /resumes/upload` persists the `Resume` row, *then* raises 402 | **LOW** | Partial write on a payment-required response: the user's upload is stored but reported as rejected, and there is no `DELETE /resumes` route to undo it. `[INFERRED — `resumes.py:105-121` code path; deliberately **not** probed live, because the row would be unremovable]` |

**What the testers got right, and wrong.** Both reports correctly observed the *symptoms*. Both drew
the wrong conclusion about the mechanism: the agent API is **not** ungated — it is one of the better
server-side gates in this codebase (gate-before-work, fail-closed, sync+async seams, constant-time
secret compare). Neither report found the one route that *is* genuinely ungated, because both inferred
"ungated" from read endpoints returning 200 rather than from tracing LLM call sites.

---

## 10. Provenance, state changes, and limits

- **Data created and removed:** one `StoryEntry` (`id: c74af947836a209d9d98b9eba`) on the test account,
  created 00:55:54Z, deleted 00:58:02Z (204), absence re-verified (`GET /api/stories` → `[]`).
  **No other production row was created, modified, or deleted.**
- **No configuration changed.** No source, `.env`, or subscription row touched. No Stripe session
  created, no payment made, no approval actioned.
- **Paid resource consumption: zero.** No agent run succeeded; `test-run` is a documented
  no-LLM cost preview.
- **Secrets:** none printed. Bearer token handled by file reference only; prefix `eyJhbGci` (JWT header)
  is the maximum disclosed.
- **Limits of this review.** The lapsed-subscriber exploitation of ADV-ENT-001 is `[INFERRED]` from the
  code path plus the 404-vs-402 differential, **not** demonstrated end-to-end — doing so would have
  required creating a paid subscription or mutating a subscription row, both out of scope. The code
  evidence is unambiguous (grep count 0 for any guard token in the router) and I regard the finding as
  established; only the live LLM burn is unproven.

**Tagging key:** `[VERIFIED]` = live probe with timestamp in §2, or exact `file:line`.
`[INFERRED]` = derived from code reading without a live probe.
