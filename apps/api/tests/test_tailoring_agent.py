"""P2-S05 — Resume tailoring agent tests (LLM record-replay mode)."""
from __future__ import annotations

from conftest import seed_own_resume

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_parser import compute_format_hash, parse_resume_pdf
from app.services.resume_tailor import _evidence_index, unsupported_tokens


def _own_operator_text() -> str:
    """The bundled operator PDF's parsed text, seeded EXPLICITLY as the fixture
    user's OWN résumé (never auto-seeded — NF-final-B-005).

    The committed ``tailor`` LLM replay fixture (``tests/fixtures/llm/tailor/
    default.json``) is a STATIC canned rewrite keyed only by prompt name; it
    targets specific ``evidenceRef`` indices (bullet-6/7/9/12/16) and wording
    that only line up with THIS résumé's 26-bullet structure. A synthetic
    résumé with different bullets/indices would make every canned rewrite miss
    its evidenceRef (or fail the anti-fabrication guard), so the run would
    always be an honest no-op — that would silently drop this suite's real
    coverage rather than test it. Explicitly POSTing this text as the user's
    own résumé (as done here) is not the auto-seed leak the fix closed: the
    user consciously supplies it, exactly like uploading a résumé that happens
    to read the same.
    """
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    return client.get("/jobs", headers=auth_headers).json()[0]


def _run_tailor(client, auth_headers) -> dict:
    seed_own_resume(client, auth_headers, raw_text=_own_operator_text())
    job = _seed_job(client, auth_headers)
    resp = client.post(
        "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTailoring:
    def test_tailoring_does_not_invent_skills(self, client, auth_headers):
        """Every accepted bullet is fully evidence-traced (D-0015 semantics)."""
        body = _run_tailor(client, auth_headers)
        resume = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        # The tailored resume is now grounded on the SEEDED (own) résumé — build
        # the evidence index from that exact same explicitly-seeded text (see
        # ``_own_operator_text`` docstring for why this test seeds that content).
        raw_text = _own_operator_text()
        stems, numbers = _evidence_index(raw_text)
        for bullet in resume["sections"]["bullets"]:
            novel = unsupported_tokens(bullet["text"], stems, numbers)
            assert not novel, f"invented tokens: {novel}"

    def test_every_changed_bullet_has_evidence_ref(self, client, auth_headers):
        body = _run_tailor(client, auth_headers)
        resume = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        for bullet in resume["sections"]["bullets"]:
            assert bullet.get("evidenceRef"), f"missing evidenceRef: {bullet}"

    def test_format_hash_unchanged_after_tailoring(self, client, auth_headers):
        before = compute_format_hash(get_base_resume_path())
        _run_tailor(client, auth_headers)
        assert compute_format_hash(get_base_resume_path()) == before

    def test_tailored_resume_is_child_of_base(self, client, auth_headers):
        body = _run_tailor(client, auth_headers)
        resume = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        assert resume["parentId"] is not None
        parent = client.get(f"/resumes/{resume['parentId']}", headers=auth_headers).json()
        assert parent["parentId"] is None  # parent is the base resume

    def test_retailoring_corrupted_parent_stays_consistent(self, client, auth_headers):
        """A pre-fix tailored version storing two rows for one evidenceRef
        must re-tailor cleanly: unique refs in the child and the run's
        `changes` equal to what the diff endpoint reports (observed live:
        run said 7, diff said 6)."""
        from app.repositories.resume import ResumeRepository
        from app.security import decode_access_token
        from app.services.resume_pdf import extract_pdf_bullets

        job = _seed_job(client, auth_headers)
        token = auth_headers["Authorization"].removeprefix("Bearer ")
        user_id = decode_access_token(token)["userId"]
        repo = ResumeRepository()
        # Build the corrupted parent from the REAL base résumé content (which the
        # default LLM fixture rewrites, so the re-tailor produces genuine changes
        # rather than an honest no-op — MV-resume-studio-003) and inject the
        # pre-fix corruption: a SECOND row for an existing evidenceRef (bullet-6,
        # one the fixture rewrites). _structure_originals must dedup it (first row
        # wins) so the duplicate never propagates to the child.
        base_path = get_base_resume_path()
        base_raw = parse_resume_pdf(base_path)["raw_text"]
        base_bullets = [
            {"text": b, "evidenceRef": f"bullet-{i}"}
            for i, b in enumerate(extract_pdf_bullets(base_path))
        ]
        dup = dict(base_bullets[6])
        dup["text"] = dup["text"] + " (duplicate row)"
        corrupted = repo.create(
            user_id,
            {"raw_text": base_raw, "bullets": base_bullets + [dup]},
            "corrupthash",
            label="Corrupted pre-fix version",
            version=repo.next_version(user_id),
        )
        resp = client.post(
            "/agents/tailor/run",
            json={"job_id": job["id"], "resume_id": corrupted["id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        child = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        refs = [b["evidenceRef"] for b in child["sections"]["bullets"]]
        assert len(refs) == len(set(refs)), f"duplicate refs propagated: {refs}"
        diff = client.get(f"/resumes/{body['resume_id']}/diff", headers=auth_headers).json()
        assert body["changes"] == len(diff["changes"])

    def test_resume_list_and_diff_endpoints(self, client, auth_headers):
        body = _run_tailor(client, auth_headers)
        resumes = client.get("/resumes", headers=auth_headers).json()
        assert len(resumes) >= 2  # base + tailored
        diff = client.get(f"/resumes/{body['resume_id']}/diff", headers=auth_headers)
        assert diff.status_code == 200
        assert "changes" in diff.json()
        download = client.get(
            f"/resumes/{body['resume_id']}/download", headers=auth_headers
        )
        assert download.status_code == 200
        assert download.headers.get("content-type") == "application/pdf"
