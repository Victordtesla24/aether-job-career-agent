# FEAT-B2 — Move applications between stages — PRODUCTION verification

- Date (UTC): 2026-07-23T21:23Z
- Environment: https://5cb5f0620.abacusai.cloud (live prod, deploy SHA `abb8e92`)
- Actor: admin user `c6c8d0163d973a8048e7e33b8` (fresh login token; all calls owner-scoped)
- Endpoints under test: `POST /applications/{id}/move`, `POST /applications/pipeline/{job_id}/move`

## 1. Application-card move (POST /applications/{id}/move)
App `cf59ef7ac35581faeb04f9083` ("Sr. Engagement Manager", Databricks), initial `status: submitted`.

### Move to `interview` → 200, status persisted
```
POST /applications/cf59ef7ac35581faeb04f9083/move {"to_stage":"interview"}
→ HTTP 200, response status: "interview"
GET /applications/cf59ef7ac35581faeb04f9083 → status: interview   (persisted re-read)
```

### Move back to `submitted` → 200, original state restored
```
POST .../move {"to_stage":"submitted"} → HTTP 200
GET re-read → status restored: submitted
```

## 2. Honest 422s on illegal application-card moves (status untouched)

### Job-status-fed stage rejected
```
POST .../move {"to_stage":"discovered"}
{"detail":"Stage 'discovered' is Job-status-fed — a application card cannot move there. Valid targets for a application card: ['in-review', 'interview', 'offer', 'ready', 'submitted']"}
HTTP 422
```

### Unknown stage rejected
```
POST .../move {"to_stage":"bogus"}
{"detail":"Unknown stage 'bogus'. Valid stages: ['discovered', 'evaluating', 'in-review', 'interview', 'offer', 'ready', 'submitted', 'tailoring']"}
HTTP 422
```

### App status untouched after both 422s
```
GET re-read → status: submitted
```

## 3. Job-card (pipeline) move (POST /applications/pipeline/{job_id}/move)
Job `cb82d1091f294eb6a3b685923` ("Principal Business Technology Product Ma…"), no application, initial `status: discovered`.

### Move to `evaluating` → 200, job status becomes `screening`
```
POST /applications/pipeline/cb82d1091f294eb6a3b685923/move {"to_stage":"evaluating"}
{"id":"cb82d1091f294eb6a3b685923","status":"screening","stage":"evaluating"}
HTTP 200
GET /jobs/cb82d1091f294eb6a3b685923 → status: screening   (persisted re-read)
```

### Move back to `discovered` → 200, restored
```
POST .../move {"to_stage":"discovered"}
{"id":"cb82d1091f294eb6a3b685923","status":"discovered","stage":"discovered"}
HTTP 200
GET re-read → status restored: discovered
```

## 4. Pipeline-move guardrails

### Job that already has an application → honest 409
```
POST /applications/pipeline/c056a75ffc4b09c92fa8531e7/move {"to_stage":"evaluating"}
{"detail":"This job already has an application — move the application card instead."}
HTTP 409
```

### Application-status-fed stage for a job card → honest 422
```
POST /applications/pipeline/cb82d1091f294eb6a3b685923/move {"to_stage":"interview"}
{"detail":"Stage 'interview' is Application-status-fed — a job card cannot move there. Valid targets for a job card: ['discovered', 'evaluating', 'tailoring']"}
HTTP 422
```

## 5. Analytics consistency
`GET /applications/funnel/sankey` was captured BEFORE and AFTER the full sequence above.
All moves were reverted, and the two sankey snapshots are byte-identical
(`diff` → no output → "SANKEY UNCHANGED"), confirming the move endpoints feed the same
status fields analytics reads and left no residue.

## Verdict
FEAT-B2 verified live: legal moves 200 + persisted for both application cards and
pipeline job cards, illegal/unknown moves honest 422 with actionable detail, pipeline
move on an applied job honest 409, no state corruption, analytics consistent.
