# PHASE 0 Step 3 — Production Health Probe

- Timestamp: 2026-07-23T15:41:00Z
- Endpoint derivation: `apps/api/app/routers/health.py` line 24 — `@router.get("/health", response_model=HealthResponse)`; router has no prefix (`APIRouter(tags=["health"])`, line 14) and is included in `apps/api/app/main.py` line 201. nginx (`/etc/nginx/conf.d/5cb5f0620.conf`) rewrites `/api/(.*) → /$1` to uvicorn on 127.0.0.1:8000, so the public path is `/api/health`.

## Transcript (2026-07-23T15:41:00Z)

```
$ curl -sS -w '\nHTTP %{http_code} time %{time_total}s\n' https://5cb5f0620.abacusai.cloud/api/health
{"status":"ok","version":"0.2.0"}
HTTP 200 time 0.058524s

$ curl -sS -w '\nHTTP %{http_code} time %{time_total}s\n' -H 'Host: 5cb5f0620.vm.internal' http://localhost/api/health
{"status":"ok","version":"0.2.0"}
HTTP 200 time 0.001579s

$ curl -sS -w '\nHTTP %{http_code} time %{time_total}s\n' http://127.0.0.1:8000/health
{"status":"ok","version":"0.2.0"}
HTTP 200 time 0.001524s
```

## Verdict

`[VERIFIED-WITH-FRESH-EVIDENCE]` — production, nginx-ingress, and direct-uvicorn probes all return HTTP 200 with `{"status":"ok","version":"0.2.0"}`. Gate condition (200/ok) satisfied; no env fix required.
