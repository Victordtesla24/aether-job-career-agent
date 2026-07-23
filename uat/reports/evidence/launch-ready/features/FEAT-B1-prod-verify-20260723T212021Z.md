# FEAT-B1 prod verification — single delete + bulk purge-expired
Run: 20260723T212021Z UTC · host: https://5cb5f0620.abacusai.cloud · deploy: abb8e92 · user: admin

## 1. Create a dedicated approval (POST /approvals)
```json
{
    "id": "c79f53855db16fdb0d1a6e445",
    "userId": "c6c8d0163d973a8048e7e33b8",
    "applicationId": null,
    "type": "application_submit",
    "status": "pending",
    "payload": {
        "kind": "cover_letter",
        "company": "Evidence Co",
        "jobTitle": "PROD-VERIFY-B1"
    },
    "createdAt": "2026-07-23T21:20:22.204000",
    "resolvedAt": null
}
```

## 2. DELETE while live-pending → honest 409 (gate cannot be bypassed)
```
{"detail":"Approval is still pending and not expired — approve or reject it instead of removing it."}
HTTP 409
```

## 3. Reject (resolve), then DELETE → 200 with the deleted row
```
reject HTTP 200
{"id":"c79f53855db16fdb0d1a6e445","userId":"c6c8d0163d973a8048e7e33b8","applicationId":null,"type":"application_submit","status":"rejected","payload":{"kind":"cover_letter","company":"Evidence Co","jobTitle":"PROD-VERIFY-B1"},"createdAt":"2026-07-23T21:20:22.204000","resolvedAt":"2026-07-23T21:20:22.789000"}
HTTP 200
```

## 4. Second DELETE of the same id → honest 404 (hard-deleted, no zombie row)
```
{"detail":"Approval not found"}
HTTP 404
```

## 5. Bulk purge-expired (POST /approvals/purge-expired)
Setup: created approval `cd5ccdbbf4f67ab27362b3ef7` then backdated ITS OWN createdAt by 49h via a single owner-scoped SQL UPDATE (WHERE id + userId) — server-side expiry (48h) then decides the purge; no client-side trickery.

### Pending+expired set BEFORE purge (server data, 48h cutoff)
> Note (honest gap): the helper script that was meant to print the pre-purge expired set crashed
> (naive/aware datetime comparison TypeError) and produced no output, so no "before" listing was
> captured. The purge response below is the authoritative record of what was expired at call time:
> it names all 3 purged ids, including the backdated setup row `cd5ccdbbf4f67ab27362b3ef7` plus two
> pre-existing genuinely-expired pending rows belonging to the same admin user.

### Purge call
```
{"purged":3,"ids":["c5a684c61a05fd5c269abb806","cd5ccdbbf4f67ab27362b3ef7","c686772c94212b36276d77a8e"]}
HTTP 200
```

### Second purge immediately after → honest zero (nothing left to purge)
```
{"purged":0,"ids":[]}
HTTP 200
```

### Purged row is really gone (GET → 404)
```
{"detail":"Approval not found"}
HTTP 404
```
