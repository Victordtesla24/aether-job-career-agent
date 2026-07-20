# Raw API probe transcripts — MV-networking

All probes run against https://5cb5f0620.abacusai.cloud/api with admin/admin123 bearer token.

## Field-mapping mismatch proof — GET /workspaces/networking/summary outreachQueue item
```json
{
  "id": "c8583b37c7bbd84d51c812896",
  "kind": "follow_up",
  "status": "pending",
  "contactName": "MV-networking-ProbeContact",
  "company": "MV Probe Co",
  "subject": "Follow Up — MV Probe Co",
  "scheduledAt": null,
  "sentAt": null
}
```
Frontend `NetworkingSummary.outreachQueue` type (apps/web/src/lib/api/workspaces.ts) expects
`{ to, subject, preview, tone }`. Only `subject` overlaps -> `to`/`preview`/`tone` render as blank/undefined.

## Field-mapping mismatch proof — communicationLog item (status=sent)
```json
{
  "id": "cf0aa6bd41a88a7f2fc0425c3",
  "kind": "introduction",
  "status": "sent",
  "contactName": "MV-networking-CommLogProbe",
  "company": "MV Probe Co2",
  "subject": "Introduction — MV Probe Co2",
  "scheduledAt": null,
  "sentAt": "2026-07-17 16:20:38.152543+00:00"
}
```
Frontend `communicationLog` type expects `{ when, who, channel, note }` — zero overlap. All 4 fields
render as `undefined` (blank) in the Communication Log card.

## Referential-integrity gap — POST /networking/outreach with nonexistent contact_id
Request: `{"contact_id":"nonexistent-mv-test-id","type":"message"}`
Response: HTTP 201
```json
{"id":"c2c61a83235612aa25e65ad6b","userId":"cc29a76e324fbf19f438eb8be","contactId":"nonexistent-mv-test-id","type":"message","status":"pending","message":null,"scheduledAt":null,"sentAt":null,"createdAt":"2026-07-17T16:19:21.495506Z","updatedAt":"2026-07-17T16:19:21.495506Z"}
```
Expected: 404/422 rejection (contact does not exist) or DB-level FK violation surfaced as 4xx/5xx.
Observed: silently accepted despite `OutreachTask.contactId` being declared
`REFERENCES "Contact"("id") ON DELETE CASCADE` in apps/api/app/routers/networking.py:71.

## Referential-integrity gap — orphan survives contact deletion
1. Created contact `c4423ff69a64f4627e6b1fef4`.
2. Created outreach task `c178fae7316a1d540851d9561` referencing it.
3. Deleted the contact via `DELETE /networking/contacts/c4423ff69a64f4627e6b1fef4` -> 204.
4. `GET /networking/outreach` still returned the task, `contactId` pointing at the now-deleted contact:
```json
[{"id":"c178fae7316a1d540851d9561","userId":"cc29a76e324fbf19f438eb8be","contactId":"c4423ff69a64f4627e6b1fef4","type":"follow_up","status":"pending","message":"MV-networking-test-outreach-message","scheduledAt":null,"sentAt":null,"createdAt":"2026-07-17T16:18:19.508101Z","updatedAt":"2026-07-17T16:18:19.508101Z"}]
```
Expected (per declared DDL): row cascade-deleted. Observed: orphan row remained until
manually deleted by this tester (`DELETE /networking/outreach/c178fae7316a1d540851d9561` -> 204).

## Validation sanity checks (all behaved correctly / honestly)
- POST contact, name = 315-char string -> 422 `string_too_long` (max_length=200 enforced). Correct.
- POST contact, stage="not-a-real-stage" -> 422 with valid-values list. Correct.
- GET contact by nonexistent id -> 404 `{"detail":"Contact not found"}`. Correct.
- PATCH contact with empty JSON body `{}` -> 200, no-op, record unchanged. Honest (no destructive no-op).
- XSS probe: contact name = `MV-networking-XSS-<img src=x onerror=alert(1)>` -> stored verbatim, but
  rendered in the DOM as escaped text (React auto-escaping); no `alert()` dialog fired; raw `<img ...>`
  tag absent from rendered HTML. XSS-safe.
