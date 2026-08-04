# ADR-CRITICAL-3b — an upstream credit failure stops being reported as the customer's quota

- **Status:** Implemented (fix landed; gate closure is not this document's to assert)
- **Date:** 2026-08-04
- **Finding:** CRITICAL-3b — BLOCKING item of the adversarial review of `0b6102d`
  (`fix(CRITICAL-3): the tailor agent hot-looped 60 paid calls/hour at an upstream returning 402`)
- **Authorship:** the fix, its docstrings and all nine backend tests were authored by
  **session B** and left in deliberate "red proof" mode (both call sites disabled, with an
  honest `RED-PROOF-TEMP` comment). This change **enables** that work, adds nothing to its
  logic, and lands it with its tests. See §7.
- **Surfaces:** `POST /agents/{name}/run` and the async enqueue path
  (`_record_run`, `_enqueue_single_agent`), the autopilot (`workers/board_sweep.py`),
  and the Agents-screen error banner (`apps/web/src/lib/agents-feedback.ts`).
- **Fix evidence:** see §6 (test logs, fail-before/pass-after).

---

## 1. What the defect did

`0b6102d` added an LLM circuit breaker. It parks its cooldown in the **same
`AgentQuotaBlock` row** that already carried subscription-quota cooldowns, distinguished
only by `reason`:

| `reason` | Meaning | Correct answer |
| --- | --- | --- |
| anything else | the **user's** provider subscription quota is spent | HTTP 429, their reset time, "switch to API-key billing" |
| `llm_circuit_open:<class>` (`CIRCUIT_REASON_PREFIX`, `llm_client.py:1287`) | **our** upstream refused — 402 out of credits / 401 bad key — and we stopped asking | HTTP 503, an operator problem, never billed to the user |

`LLMClient._call_live` learned to read that prefix. The two **router gates** that consult
the same row before every run did not — they raised `_quota_429(...)` for *any* active row.
The first attempt is unaffected (the breaker is still closed, so the failure travels the
`LLMUnavailableError` path); from the **second attempt onward**, an upstream HTTP 402 was
reported to a paying customer as:

> "Your openrouter subscription quota is exhausted. Runs are paused until it resets."
> — *suggestion:* "Switch this agent to API-key billing in Agent Settings."

Every clause of that is false for a 402. It blames the customer for an operator failure and
prescribes a remedy that cannot work.

It also corrupted the operator's own telemetry. `board_sweep.sweep_user_stretch` special-cases
`HTTPException(429)` as `reason="quota-exhausted"` **before** it ever consults `_llm_failure`
(`board_sweep.py:792-796`), so from tick 2 the autopilot's own record agreed with the lie and
hid the dead upstream that the breaker exists to make visible — and, because a 429 carried no
`__cause__`, the failure class and the honest `suppressed` count stopped being reported at all.

## 2. The fix

One seam, in one place, read by both gates.

**`apps/api/app/services/llm_client.py`**

- `is_circuit_block(block)` (`:1356`) — the single authority on what a block row *means*.
- `circuit_block_error(provider, block)` (`:1381`) — returns the classified
  `LLMCircuitOpenError` for a circuit row, or `None` when the row is a genuine
  subscription-quota block and the caller must keep its 429.
- `_call_live` (`:2484`) now uses that seam instead of its own inline prefix check —
  behaviour-identical, so the reason-parsing exists exactly once.

**`apps/api/app/routers/agents.py`**

- `_raise_if_llm_circuit_open(provider, block)` (`:678`) raises the same honest,
  class-specific 503 the in-run failure path raises (`llm_failure_user_message`), so the
  customer sees one consistent story on attempt 1 and attempt 2:
  - `insufficient_credits` → "The AI provider rejected the request because the account is
    out of credits… retrying now will not help." (no upgrade CTA, no quota claim)
  - `auth` → "…rejected the configured credential (authentication failed)…"
  - anything else, including a circuit row whose class we cannot read → the unchanged
    transient message, i.e. retry with backoff. Degrading *down* to transient is deliberate:
    an unreadable class must never become a permanent-sounding claim we cannot support.
- Called from both gates before the existing `_quota_429`: `_record_run` (`:899`) and
  `_enqueue_single_agent` (`:2131`). A genuine subscription-quota row falls straight through
  and keeps its 429, its `retryAfter` and its CTA — pinned by
  `test_a_genuine_subscription_quota_block_still_raises_the_429`.

**`apps/web/src/lib/agents-feedback.ts`**

`runErrorNotice` discarded every 503 body and rendered one hardcoded line — "the AI model is
busy or its time budget was exceeded. Wait a minute and press the button again". Landing the
backend alone would have replaced a false 429 with a truthful 503 that the UI then overwrote
with different false copy, so the customer-visible half is part of the same fix. It now
prefers a genuine backend `{"detail": …}` body (strict extractor: a synthetic client-side
error or a gateway 503 with no JSON detail still falls through to the original guidance).

### Three properties this fix must not lose

1. **`raise … from circuit` is load-bearing, not cosmetic.** It sets `__cause__`, which is how
   `board_sweep._llm_failure` (`board_sweep.py:582-624`) recovers the failure class *through
   the HTTP translation*. With the class recovered and `retryable is False`, the sweep calls
   `_abort_on_llm` — reason `llm-insufficient_credits`, `suppressed` = the eligible jobs left
   deliberately unattempted — instead of counting an ordinary failure or claiming a quota stop.
   Verified end-to-end by `TestBoardSweepSecondTick` against a real local HTTP server
   answering 402 across two sweep ticks, and directly by
   `test_the_gate_carries_the_failure_class_for_the_autopilot`.
2. **The refusal precedes every charge.** Both gates run the block check *before* the atomic
   `UsageQuotaRepository.reserve` and before the `AgentRun` row exists
   (`_record_run` :890-938, `_enqueue_single_agent` :2119-2143), so a run refused because our
   upstream is out of credit consumes nothing of the customer's plan and leaves no audit row.
   Pinned by `test_the_open_circuit_gate_consumes_no_plan_quota_and_writes_no_run` and, on the
   async path, by the `_runs_used` assertion in `TestAsyncEnqueueGate`.
3. **Only circuit rows are narrowed.** `circuit_block_error` returns `None` for everything
   else, so the change cannot become a general "stop showing 429s" patch.

## 3. Why 503 and not 402/429

The customer has done nothing wrong and there is nothing they can pay to fix. 429 asserts
"you exceeded a limit"; 402 asserts "you owe money". The failing party is the service, which
is exactly what 503 says, and it is already the status the *first* attempt returns through
`LLMUnavailableError` — so the two attempts now agree.

## 4. Rejected alternatives

- **Read `reason` inline at both gates.** Two copies of the same prefix parse; `_call_live`
  would have made three. The bug *was* a second reader that did not know the rule.
- **A separate cooldown table for the breaker.** Additive DDL and a migration for a
  distinction the `reason` column already carries; does not fix the readers, which is the bug.
- **Keep the 429 and only reword it.** The status code is what `board_sweep` branches on, so
  a reworded 429 leaves the operator's telemetry lying and the autopilot mis-stopping.
- **Delete the six failing tests to reach a green suite.** No tracked test covered this
  defect, so that would have left it live *and* unguarded.

## 5. Blast radius

`_raise_if_llm_circuit_open` can only fire when an `AgentQuotaBlock` row's `reason` starts
with `llm_circuit_open:` — a prefix written by exactly one function
(`_record_llm_circuit_open`). Every other block row reaches `_quota_429` on the identical
path it did before. The `_call_live` edit is a refactor to the shared seam with no behaviour
change. The web change is gated on a 503 *with* a parseable backend detail.

## 6. Verification (this tree, 2026-08-04)

| Suite | Before | After |
| --- | --- | --- |
| `tests/test_critical3b_credit_block_is_not_a_user_quota_block.py` | **6 failed**, 3 passed | **9 passed** |
| `tests/test_gm2s15_f04_probability_self_reference.py` (separate defect, §8) | 1 failed (`UniqueViolation` in arrange), 2 passed | **3 passed** |
| circuit breaker + billing + paywall + board sweep + autopilot suppression + agents screen + SSE + reconcile + served-model billing + upload quota + email-agent quota + market-pulse + interview conversion (16 files) | — | **210 passed, 1 skipped** |
| `apps/web` `src/__tests__/dashboard/` (13 files) | 3 failed of the 4 CRITICAL-3b cases against the pre-fix module | **88 passed** |

`ruff` and `mypy` clean on the changed Python; `tsc --noEmit` clean on the web app.
The web fail-before was measured against `git show HEAD:…/agents-feedback.ts` loaded under a
temporary module name, never by overwriting the working tree.

## 7. Attribution

`_raise_if_llm_circuit_open`, `is_circuit_block`, `circuit_block_error`, the `_call_live`
refactor, the nine backend tests and the four web tests are **session B's** work, written
2026-08-03 and left disabled with an honest `RED-PROOF-TEMP` marker so the tests would prove
the defect red. Reviewing that code for this ADR found **no flaw**: it was correct as written
and is enabled unchanged. This change contributes the two call-site enables, the removal of
the two now-false `RED-PROOF-TEMP` comments, the verification above and this document.

## 8. Not part of this ADR

`tests/test_gm2s15_f04_probability_self_reference.py::test_3` was landed (with `5f9e775`)
seeding four `submitted` and then four `interview` Application rows on the **same four jobs**,
which the partial unique index `Application_user_job_active_key` (`app/db.py`,
`ensure_application_unique_active_index`) forbids. It therefore died in its arrange step and
never reached its score comparison — so `5f9e775`'s only anti-over-correction guard was
vacuous, and the file's docstring claim that test 3 "already passes" was never observable.
Fixed in its own commit by promoting the existing applications (what `move_application` does
in production) instead of duplicating them, reusing the `WC-INTERVIEW-SEED-001` guard pattern
from `tests/test_wc_interview_conversion_rate.py`, and correcting the docstring.

## 9. Residual

- **Not deployed.** The deploy window is held elsewhere; all four units (`aether-api`,
  `aether-web`, `aether-worker`, `aether-discovery`) run from this tree and a deploy is only
  complete when every one has restarted (GOV-028). Until then production still answers the
  second attempt with the user-blaming 429.
- **Not verified against production.** Every number in §6 is from this tree.
- The breaker's cooldown still shares a table with subscription-quota cooldowns. That is now
  safe because both readers go through one seam, but any *new* reader of `AgentQuotaBlock`
  must call `is_circuit_block` — the class of bug this ADR describes is a missing reader, not
  a wrong branch.
