"""CLI-QP — the quality policy must compute conversion over VERIFIED submissions.

Audit finding: `collect_policy_metrics` counted every non-draft application as
"submitted", so a conversion rate was computed over ~390 recorded-but-never-
transmitted phantom applications (0.3% over rows that never left the building),
and the tier-escalation policy tightened agent rigor on that fiction. The honest
denominator is jobs with a real `transmittedAt`.
"""
from __future__ import annotations

import json

from app.db import get_connection, new_id
from app.services.quality_policy import collect_policy_metrics


def _job(cur, uid: str) -> str:
    jid = new_id()
    cur.execute(
        'INSERT INTO "Job" ("id","userId","title","company","description","source",'
        '"sourceUrl","createdAt","updatedAt") '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,now(),now())',
        (jid, uid, "Eng", "Acme", "Build things.", "test", f"https://x/{jid}"),
    )
    return jid


def _resume(cur, uid: str) -> str:
    rid = new_id()
    cur.execute(
        'INSERT INTO "Resume" ("id","userId","sections","formatHash","createdAt",'
        '"updatedAt") VALUES (%s,%s,%s::jsonb,%s,now(),now())',
        (rid, uid, json.dumps([]), "h0"),
    )
    return rid


def _app(cur, uid: str, jid: str, rid: str, *, transmitted: bool) -> None:
    cur.execute(
        'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
        '"transmittedAt","createdAt","updatedAt") VALUES '
        "(%s,%s,%s,%s,'submitted'::\"ApplicationStatus\","
        + ("now()" if transmitted else "NULL")
        + ",now(),now())",
        (new_id(), uid, jid, rid),
    )


def test_phantom_submissions_do_not_count_toward_sample_size(client, auth_headers):
    from app.security import decode_access_token

    uid = decode_access_token(auth_headers["Authorization"].removeprefix("Bearer "))["userId"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            rid = _resume(cur, uid)
            # 3 phantom "submitted" apps that never transmitted + 1 real transmission.
            for _ in range(3):
                _app(cur, uid, _job(cur, uid), rid, transmitted=False)
            _app(cur, uid, _job(cur, uid), rid, transmitted=True)
        conn.commit()

    metrics = collect_policy_metrics(uid)
    assert metrics["available"] is True
    # Only the 1 real transmission counts — NOT the 3 phantom "submitted" rows.
    assert metrics["sampleSize"] == 1, (
        f"sampleSize should count only verified transmissions, got {metrics['sampleSize']}"
    )
