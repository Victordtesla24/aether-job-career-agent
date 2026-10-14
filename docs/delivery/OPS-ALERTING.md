# OPS-ALERTING — operator email alerts on prod unit failure (D-ALERT)

**Status:** code-complete. Every file this ticket adds lives under `scripts/`
and `deploy/` in the repo; installing is a separate, explicit deploy-window
action — see §3.

**Status update 2026-10-14 (D-ALERT-2):** this wiring was installed on the
Abacus VM that served production until the 2026-08-17 migration and was never
removed from it. On 2026-10-13 that VM's `aether-web.service` began crash-looping
(`next start`: no production build in `.next`), and because the alert was one
email per failed start with no limit it sent 215 emails in four hours,
exhausting the shared Resend quota so that the application's own welcome email
was rejected (`daily_quota_exceeded`). The script is now throttled (§6) and the
three crash-looping units stop after five starts in five minutes (§1). The
Hostinger VPS production units (`aether-prod-*`) do not use this wiring; they
are supervised by the environment guardian, which reports to the orchestrator
inbox.

## 1. What this is

Today, a failed `aether-api` / `aether-worker` / `aether-web` /
`aether-discovery` unit on the prod VM is silent until someone happens to
check `systemctl status` or tail `/var/log/aether/*.log`. This wires
systemd's own `OnFailure=` hook so any of those units failing sends **one
email** to the operator, using the outbound-email provider the app already
has configured (`AETHER_EMAIL_API_KEY` / `AETHER_EMAIL_FROM`, the
Resend-style HTTPS API documented in `docs/delivery/EMAIL-SETUP.md` and
implemented in `apps/api/app/services/email_sender.py::_send_via_api`). No
new service, no new credential, no new dependency.

### Files added

| File | Purpose |
|---|---|
| `scripts/ops_alert.sh` | Sends the alert email. Takes the failed unit's name as `$1`. |
| `deploy/aether-alert@.service` | `Type=oneshot` template unit; `ExecStart` runs `ops_alert.sh %i`. |
| `deploy/systemd-dropins/<unit>.service.d/10-onfailure.conf` | One per watched unit (`aether-api`, `aether-worker`, `aether-web`, `aether-discovery`, `aether-email-agent`) — adds `OnFailure=aether-alert@%n.service` to that unit without touching its own `.service` file. |

### How it fires

1. A watched unit (e.g. `aether-api.service`) fails.
2. Its `10-onfailure.conf` drop-in tells systemd to start
   `aether-alert@aether-api.service.service` (the `%n` expands to the failed
   unit's own full instance name).
3. That instantiates `aether-alert@.service`, which runs
   `scripts/ops_alert.sh aether-api.service`.
4. The script first applies the throttle (§6: one email per unit per hour, at
   most 10 per UTC day across all units) and stops here when it suppresses.
   Otherwise it reads `AETHER_EMAIL_API_KEY` / `AETHER_EMAIL_FROM` out of the
   repo-root `.env` (single-key `grep`, never a wholesale `source` — same
   extraction idiom as `scripts/run-tests.sh` / `scripts/env-audit.sh`),
   tails the last 40 lines of that unit's log file
   (`/var/log/aether/<short-name>.log`, derived by stripping the
   `aether-`/`.service` wrapping — matches the `logging.conf` drop-ins each
   unit already writes to) if present, and POSTs one email to
   `sarkar.vikram@gmail.com` via `https://api.resend.com/emails`.
5. The script always `exit 0`s, whether or not the send succeeded — an
   alerting script that itself crash-loops (and, per `Restart=` policies on
   some of these units, could even re-trigger `OnFailure` on itself) is
   strictly worse than a swallowed send failure. Send failures are logged to
   stderr (captured by the `aether-alert@` unit's own journal entry) without
   ever printing the API key.

## 2. Local validation already done (this ticket)

```bash
bash -n scripts/ops_alert.sh   # syntax check — passed
shellcheck scripts/ops_alert.sh  # 0.9.0 — zero warnings, zero errors
```

The two code paths inside the script were also exercised directly on this
VM: the "no `AETHER_EMAIL_API_KEY`/`AETHER_EMAIL_FROM` configured" branch
(run with an isolated `.env`-less copy — logs to stderr, exits 0, sends
nothing), and the log-file-present vs. log-file-missing branch (checked
against the real `/var/log/aether/{api,worker,web,discovery}.log`, which all
exist, vs. `email-agent.log`, which correctly does not since that unit isn't
deployed yet).

## 3. Install (deploy window only — not run by this ticket)

Run these **on the prod VM**, from the repo root, once this branch is merged
to the branch actually deployed there:

```bash
cd /home/ubuntu/github_repos/aether-job-career-agent

# 1. The alert-dispatcher template unit.
sudo ln -sf "$(pwd)/deploy/aether-alert@.service" /etc/systemd/system/aether-alert@.service

# 2. One OnFailure drop-in per watched unit. Each target .d/ directory may
#    already exist (aether-api/-web/-discovery already carry a logging.conf
#    drop-in there) — mkdir -p is safe either way, and this ADDS a second
#    file in that directory rather than replacing logging.conf.
for unit in aether-api aether-worker aether-web aether-discovery aether-email-agent; do
  sudo mkdir -p "/etc/systemd/system/${unit}.service.d"
  sudo ln -sf "$(pwd)/deploy/systemd-dropins/${unit}.service.d/10-onfailure.conf" \
    "/etc/systemd/system/${unit}.service.d/10-onfailure.conf"
done

# 3. State directory for the throttle (§6). Optional: without it the script falls
#    back to a private directory under /tmp, which is lost at reboot.
sudo install -d -o ubuntu -g ubuntu -m 0750 /var/lib/aether-alert

# 4. Pick up the new/changed unit files. aether-api, aether-web and aether-worker
#    are copied, not symlinked, so re-copy them after a change to deploy/*.service
#    (their StartLimit*/RestartSec settings only apply after a daemon-reload).
sudo systemctl daemon-reload
```

No `systemctl enable`/`restart` of the *watched* units is required — a
drop-in changing their `[Unit]` section is picked up by `daemon-reload`
alone; it only takes effect the next time that unit actually fails (or on
its next start, for the `OnFailure=` wiring itself to be in place before a
failure — a running unit does not need to be restarted for a `[Unit]`
drop-in to register, but if in doubt `systemctl restart <unit>` is harmless
in the deploy window since these units already restart routinely).

`aether-email-agent.service` itself does not exist on the VM yet
(`docs/delivery/SESSION-COORDINATION.md` B5, still `deploy/`-only/CLAIMED) —
step 2's `mkdir -p` for it is a no-op today; its drop-in activates
automatically once that unit ships, with no follow-up alerting PR needed.

## 4. Test-fire recipe

After installing (§3), fire the dispatcher directly — this exercises the
exact same path a real failure would take, without needing to actually break
a production unit:

```bash
sudo systemctl start aether-alert@test.service
```

**Expected evidence:**

- The command returns immediately (`Type=oneshot`, and `ops_alert.sh` always
  exits 0 — `systemctl start` will not report a failure even if the send
  itself failed).
- `sudo systemctl status aether-alert@test.service` shows
  `ConditionResult=yes` / `Active: inactive (dead)` with an exit code of `0`.
- `sudo journalctl -u aether-alert@test.service -n 20 --no-pager` shows the
  script ran with unit name `test` — if `AETHER_EMAIL_API_KEY`/
  `AETHER_EMAIL_FROM` are configured (they are, in prod — see
  `docs/delivery/EMAIL-SETUP.md`) and the send succeeded, there is **no**
  stderr line; a failed send logs `ops_alert.sh: alert send for unit 'test'
  failed (HTTP ...)` without the key.
- An email lands at `sarkar.vikram@gmail.com` within seconds, subject
  `[Aether ALERT] unit test failed on prod VM`, body starting with
  `Unit: test` and a UTC timestamp, followed by
  `--- last 40 lines of /var/log/aether/test.log ---` and (since no such
  file exists) the journal-less fallback note rather than a log excerpt —
  this is expected for the synthetic `test` instance and is exactly the
  fallback a genuinely new/renamed unit with no log file yet would also see.

A second test-fire for the same instance inside an hour is suppressed by the
throttle (§6): wait, delete `/var/lib/aether-alert/unit-<name>.state`, or run the
script by hand with `AETHER_ALERT_MIN_INTERVAL_SECS=0`.

To see the **log-excerpt** branch instead of the fallback note, fire it with
a real watched unit's name, e.g.:

```bash
sudo systemctl start aether-alert@aether-api.service.service
```

which mails the last 40 lines of `/var/log/aether/api.log` and does not
require `aether-api.service` to actually be down.

## 5. Honest limits

- **Covers unit *failures* only** — i.e. anything that makes systemd mark
  the unit itself `failed` (process exits non-zero, exceeds a configured
  timeout, crashes). It does **not** catch in-process errors that the
  process survives: an unhandled exception logged and swallowed inside
  FastAPI, a job that completes "successfully" but produced wrong output, a
  slow endpoint, elevated 5xx rate under a still-`active (running)` unit,
  etc. None of those move the systemd unit into `failed` state, so none of
  them fire this alert.
- **Throttled, not a digest.** Since D-ALERT-2 (§6) a flapping unit sends one
  email per hour (with a count of what was suppressed) instead of one per failure.
  The daily cap of 10 is shared by all units, so during a wide outage a later,
  different failure can be suppressed until 00:00 UTC. Throttle state is local
  to the host, and the quota it protects is shared with the application's own
  mail, which this script cannot see.
- **Depends on the same Resend config the app's password-reset email uses**
  — if that's ever unset or the provider is down, both this alert path and
  end-user password-reset email silently degrade together. `ops_alert.sh`
  logs that condition to stderr (captured in
  `journalctl -u aether-alert@*`) but, by design (see §1 step 5), never
  escalates it further — there is no alert-for-the-alerter.
- **In-process error tracking / APM (e.g. wiring a GlitchTip DSN into the
  API and worker processes) remains a separate, not-yet-built operator
  option** — it would close the gap this ticket's approach cannot (catching
  the errors that don't crash the unit), at the cost of a new external
  dependency this ticket deliberately avoided ("works TODAY with existing
  Resend config; no external service needed"). Tracked as a future §8-style
  operator decision, not part of this delivery.

## 6. Throttle, daily cap and state (D-ALERT-2)

Every call of `scripts/ops_alert.sh` is subject to two limits before any email
is built, so that a crash loop cannot spend the shared Resend quota:

| Limit | Default | Setting (environment of the script) |
|---|---|---|
| Per unit: minimum time between emails for the same unit | 3600 s | `AETHER_ALERT_MIN_INTERVAL_SECS` |
| Global: emails per UTC day across all units | 10 | `AETHER_ALERT_DAILY_CAP` |
| Retry after a failed send (not counted against the cap) | 600 s | `AETHER_ALERT_RETRY_AFTER_FAILURE_SECS` |
| State directory | `/var/lib/aether-alert`, else `${TMPDIR:-/tmp}/aether-alert-<uid>` | `AETHER_ALERT_STATE_DIR` |

- A suppressed call writes one line to stderr (visible with
  `journalctl -u 'aether-alert@*'`) and exits 0; it only increments the unit's
  counter. The next email for that unit begins its log excerpt with a
  `[throttle]` line: *N further alert(s) for this unit were suppressed since the
  last email (first at …, last at …)*. The email that uses up the daily cap says
  so.
- State is two small text files per host: `unit-<unit>.state`
  (`next_allowed`, `suppressed`, `first_suppressed`, `last_suppressed`) and
  `day-<YYYY-MM-DD>.count`. A `flock` on `lock` in the same directory serialises
  concurrent calls. Corrupt or unreadable values are treated as empty, invalid
  settings fall back to the defaults, and old state files are pruned.
- If no state directory can be used at all the alert is sent unthrottled with a
  warning on stderr: losing the alert would be worse than a duplicate.
- The script still always exits 0 (an `EXIT` trap guarantees it), so a throttle
  bug can never turn the alert unit itself into a failing unit.
- `apps/api/tests/test_ops_alert_throttle.py` runs the real script against a fake
  `curl` and a controlled clock (`AETHER_ALERT_NOW`, tests only) and fails against
  the previous unthrottled version.

The crash-looping units `aether-api`, `aether-web` and `aether-worker` now carry
`RestartSec=10`, `StartLimitIntervalSec=300` and `StartLimitBurst=5`: five failed
starts within five minutes leave the unit `failed`, `OnFailure=` fires once, and
systemd stops restarting it until `systemctl reset-failed <unit>` and a start. A
host without a supervisor therefore needs an operator (or a supervisor) to bring
the unit back after a long outage; that trade is deliberate, because an endless
restart loop is what produced the 2026-10-13 flood.
