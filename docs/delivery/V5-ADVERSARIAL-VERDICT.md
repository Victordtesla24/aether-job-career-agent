# v5 adversarial review — 6 reviewers, **6 of 6 FAIL**, 9 BLOCKERs

Every reviewer re-ran the tests themselves rather than trusting a commit message. Nothing below is
a self-report.

## LIVE PRODUCTION OUTAGES (operator action needed)

1. **Tailoring is 100% dead right now.** OpenRouter credit exhaustion → HTTP 402 → 503 to the user,
   continuously since 14:40Z. A reviewer's live `POST /agents/tailor/run` failed in 2.4s with no
   résumé produced. Every claim about tailoring convergence is untestable until credits are topped up.
2. **Production serves a Next.js build made 2 days ago.** Zero deployed JS chunks contain the
   realtime store, transport, badge, or `/events/stream`. So EVERY frontend fix this session — G-C
   conversion metric, the Gmail reconnect affordance, the quota wall, and all of W-RT — is committed
   but **not reachable by any user**.
3. **The async worker is running pre-fix code.** `AETHER_ASYNC_GENERATION=true`, so every tailor and
   coverLetter run executes in the ARQ worker — and that worker has not been restarted since
   2026-07-xx. Backend fixes to those agents are not live either.

## BLOCKERs by stream

**W-TAILOR-CONVERGE @a6fae64 — the "LIVE RESULT" was staged.** The single Resume row carrying a
persisted score (1 of 121) was created 07:51:33 — **41 minutes BEFORE the commit** — by an
out-of-band run of uncommitted code. No production run before or since has ever produced one. Also:
`clean_gap_keywords` does not do what the message claims (`don`, `other`, `actually`, `each`, `more`
survive into the user-facing warning), and 87 lines of W-STORY-REBUILD's code were swept in.

**W-STORY-REBUILD @8c18fdc — the guard checks the wrong thing.** The anti-fabrication guard inspects
only the `metrics` dict, never the STAR prose the product actually consumes: **15 of 17 live stories
carry numbers in their narrative that the cited résumé bullet does not evidence.** The organisation
check is a substring test over the whole résumé, not a check that the org employed the candidate for
that bullet. 117 tests pass — they pin the metrics contract and never assert grounding.

**W-CLEAN @2b7dc6b — the guard was silently narrowed.** From "token appears anywhere in the file" to
"token is an `ast.Assign` target", which misses annotated assignments; a re-added generator slips
through the new guard that the old one caught. The suite is 107/107 green while the SHIPPED audit
script exits 1 against the live database right now.

**W-RT @8b27160 — backend real, client half undeployed** (see outage 2).

**W-EMAIL-INTAKE @ef121bd — unreachable, CONFIRMED.** `emailAgent` mode `job_alerts` is invocable by
no user action anywhere. The commit touches **zero** frontend files. The 45 seek-alert jobs exist
only because an agent ran the code directly. The author's fail-before/pass-after counts were,
however, independently re-verified as HONEST.

## The orchestrator's own three fixes — also FAIL

* **BLOCKER (557739e):** the evidence gate ships but **never remediates the 52 rows it was written
  for**, and `fit_scorer` skips any job that already has a `fitScore`. The contaminated scores stay.
* **BLOCKER (db30f33):** the per-company detail cap permanently starves half of SmartRecruiters —
  list order is stable, so every sweep enriches the SAME first 40 and the rest keep a 0-char
  description forever. It also adds ~116s of sequential blocking HTTP to every sweep.
* **MAJOR (cbc0874):** the "whole-table invariant" test keys on `payload->>'transmitted'`, a field
  **no production code ever writes** — so it is not an invariant, and a legitimate send would trip it.
  Its stated user benefit is also unreachable: the Approvals UI fires `/execute` only for
  `email_send`; `application_submit` approvals are never executed from the UI at all.

## Honest conclusion

The backend work is largely real. Almost none of it is REACHABLE by a user, because the web build and
the async worker are both stale — and the one workstream that claimed live proof staged it. The
correct next action is deployment and remediation, not more building.
