# Async Background Generation — Deployer Provisioning (GAP-P7-ASYNC-001)

Authoritative design: `docs/delivery/PHASE7-ASYNC-BLUEPRINT.md`. This file is the
operational checklist for the **deployer** (the fixer added only repo files; no
Redis install, no `systemctl`, no live-`.env` edits are done in the fix commit).

Rollout order (blueprint §7.2). The code default is **`AETHER_ASYNC_GENERATION`
OFF**, so steps 1-5 land with **zero** user-facing change; flip ON only after the
J3 soak (step 7).

## 1. Python deps
```bash
/opt/abacus-python/bin/pip install -r apps/api/requirements.txt   # adds arq, redis
```

## 2. Provision Redis (loopback + password + logical DB 3)
```bash
sudo apt-get update && sudo apt-get install -y redis-server           # redis-server.service
AETHER_REDIS_PASSWORD=$(openssl rand -hex 24)
sudo install -m 0640 -o redis -g redis deploy/redis-aether.conf \
     /etc/redis/redis.conf.d/aether.conf
sudo sed -i "s/__AETHER_REDIS_PASSWORD__/${AETHER_REDIS_PASSWORD}/" \
     /etc/redis/redis.conf.d/aether.conf
sudo systemctl enable --now redis-server
redis-cli -a "$AETHER_REDIS_PASSWORD" -n 3 ping                        # expect PONG
```
If `/etc/redis/redis.conf` does not `include /etc/redis/redis.conf.d/*.conf`, append
the drop-in's directives to `/etc/redis/redis.conf` directly.

## 3. Atomic `.env` additions (repo-root `.env`, perms 600 — never logged)
Append (atomic temp-write + `os.replace` + `chmod 600`), keeping the same value of
`AETHER_REDIS_PASSWORD` used above:
```
AETHER_REDIS_PASSWORD=<the openssl value from step 2>
AETHER_REDIS_URL=redis://:<AETHER_REDIS_PASSWORD>@127.0.0.1:6379/3
AETHER_ASYNC_GENERATION=false            # keep OFF until the J3 soak passes
AETHER_LLM_WORKER_BUDGET_SECONDS=300
AETHER_LLM_WORKER_COVER_BUDGET_SECONDS=300
AETHER_LLM_WORKER_PIPELINE_BUDGET_SECONDS=480
# optional watchdog tuning (defaults shown): AETHER_JOB_STALE_SECONDS=900
```
(`.env.example` carries these keys as documentation.)

## 4. Additive DDL (`BackgroundJob`)
No manual step required: `BackgroundJobRepository._ensure_table()` lazily creates
the table + indexes on first use (ADR-TR-1, additive `CREATE ... IF NOT EXISTS`).
The `migrator` may also apply the same DDL from blueprint §2.

## 5. Worker service
```bash
sudo mkdir -p /var/log/aether && sudo chown ubuntu:ubuntu /var/log/aether
sudo cp deploy/aether-worker.service /etc/systemd/system/aether-worker.service
sudo systemctl daemon-reload && sudo systemctl enable --now aether-worker
journalctl -u aether-worker -n 30 --no-pager   # or tail /var/log/aether/worker.log
```

## 6. Canary verify (flag temporarily ON)
Set `AETHER_ASYNC_GENERATION=true` in `.env`, `sudo systemctl restart aether-api`,
enqueue one tailor run -> expect `202 {"job_id","status":"enqueued"}` -> poll
`GET /api/agents/jobs/{job_id}` @3 s -> `completed` with `tokensIn>0` and no fixture
fingerprint. Force a failure -> the reserved run is refunded. Confirm the worker
picked it up in `/var/log/aether/worker.log`.

## 7. J3 soak + flip ON
Run the 20-run soak (blueprint §7.5, GATE-11/12/13). On pass, set
`AETHER_ASYNC_GENERATION=true` permanently + `sudo systemctl restart aether-api`.

## Rollback (instant, no redeploy)
`AETHER_ASYNC_GENERATION=false` + `sudo systemctl restart aether-api` -> endpoints
revert to the synchronous 200 path immediately. Redis + worker may keep running
idle; the additive `BackgroundJob` table is harmless and stays.

## Security notes (blueprint §9)
- Redis bound to `127.0.0.1` + `requirepass` + DB 3; nginx never proxies Redis.
- Worker logs `type(e).__name__` + message only — never tokens/secrets.
- Worker failure writes an honest error string only — never fixture content.
- Redis-down at enqueue -> honest 503 + refund; never a silent success/degrade.
