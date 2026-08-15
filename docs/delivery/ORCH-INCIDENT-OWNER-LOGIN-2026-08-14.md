# INCIDENT — owner login password silently rotated by §14.7 boot rotation (2026-08-14)

**Status:** Root-caused, no intruder. Cross-session RCA by ORCH-EXEC at 16:5xZ after a report from
session 9c6a2ba6's QA agent. **Operator action required** (see bottom).

## What happened

The documented owner login (`sarkar.vikram@gmail.com` / `AetherDemo1`) stopped working today.
Timeline (all UTC, from `/var/log/aether/api.log` + `systemctl show`):

| Time | Event |
|---|---|
| 04:01:57 | Repo `.env` modified — `AETHER_ADMIN_PASSWORD_HASH` is set in it (BLOCKER-001-class remediation by the concurrent session's program, plausibly its S-FIX-D window). |
| 13:31:44 | aether-api boot. `apply_admin_rotation` (apps/api/app/repositories/admin.py:893+, step 3) **writes the configured hash onto the `AETHER_ADMIN_EMAIL` row on every healthy boot** — `AetherDemo1` most plausibly died here. |
| 15:16:20 | Successful login from 127.0.0.1 — the discovery cron, which reads its password from env (`scripts/discovery_cron.sh:44-50`), unaffected by rotation. |
| 16:23:41–16:31 | QA agent's `AetherDemo1` logins 401; it manually reset `User.passwordHash` to bcrypt(AetherDemo1) at 16:31:45 via DB. |
| 16:33:26/33 | Unclaimed aether-api restart; boot rotation **overwrote the manual reset again**, by design. |
| 16:33:54 | Successful login (holder of the configured password). |

## Root cause

Working as coded: §14.7 rotation re-asserts `AETHER_ADMIN_PASSWORD_HASH` onto the admin/owner row
at every boot (ADR-BLOCKER-001 de-privilege design; the "never touch passwordHash" clause applies
only to the degraded path). The surprise came from (a) the `.env` hash being changed at 04:01:57Z
without the documented owner password being updated anywhere, and (b) two **unclaimed** prod
restarts (16:23:08, 16:33:33 — GOV-019 class, flagged to the owning session).

## Rules reaffirmed

1. **Never hand-write `User.passwordHash` on prod** — the boot rotation reverts it; you get a
   write-war with the app. Change `AETHER_ADMIN_PASSWORD_HASH` in `.env` + restart (claimed window).
2. Every restart of a prod service must be claimed in `SESSION-COORDINATION.md` first.

## Update 16:38–17:0xZ — restored again, but only boot-to-boot

Session 9c0's QA agent re-wrote `User.passwordHash` to bcrypt(AetherDemo1) at 16:38:23Z; it reads
as "stable" only because no service has restarted since 16:33:26Z. **The next aether-api boot
(any deploy, including that session's pending 9-reds fix landing) re-asserts the `.env` hash and
kills AetherDemo1 again.** Both sessions have been told; the durable fix is to align
`AETHER_ADMIN_PASSWORD_HASH` in `.env` with the operator's chosen password in a claimed window
(choosing AetherDemo1 there would partially undo the 04:01Z BLOCKER-001 strong-hash remediation —
operator tradeoff to decide).

## Operator action required (§8 ledger item)

- The owner login password is now whatever plaintext corresponds to the current
  `AETHER_ADMIN_PASSWORD_HASH` in the repo `.env` (set ~04:01:57Z today by the concurrent
  session's program — its run ledger should hold the provisioning record; this doc deliberately
  contains no credential values). `AetherDemo1` is dead unless deliberately re-provisioned via
  `.env` + restart.
- Decide the intended owner password and align: `.env` hash + any UAT/agent config that logs in
  as the owner.
