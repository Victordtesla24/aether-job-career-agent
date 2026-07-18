"""MANUAL-VERIFICATION — NF-final-B-001 / NF-final-B-002 / MV-cover-letter-studio-006.

Fail-before / pass-after coverage for THREE independent defects, all rooted in
the same anti-pattern: several user-facing agent/router paths ground on the
FIXED operator-configured resume PDF (``app/agents/fit_scorer.py::
get_base_resume_path()`` -> ``assets/resume/Vik_Resume_Final.pdf``) instead of
the calling user's OWN base résumé — a cross-account PII leak (HIGH) plus a
scoring/analytics correctness bug (MED). MV-story-bank-006 fixed only the
Story Extractor via ``StoryExtractorAgent._resolve_resume_text``; this suite
targets the remaining leaking paths (cover letter agent, fit scorer / job
insights) plus an unrelated cover-letter-studio JD-keyword-coverage defect
(garbage/boilerplate tokens crowd out real skills past the 10-item cap).

* NF-final-B-001 (HIGH)  CoverLetterAgent.run() grounds the LLM prompt on the
  operator's bundled PDF (ANZ/Telstra/$5M, real contact PII) for EVERY user,
  not the calling user's own résumé.
* (unit)                 ``app.services.resume_grounding`` does not exist yet
  (the fix introduces it) — these tests both prove that and pin its intended
  contract (own base when present; bundled fallback only when absent).
* NF-final-B-002 (MED)   FitScorerAgent / the job-insights endpoint score
  every user's jobs against the operator's fixed résumé, so matched skills
  reflect the OPERATOR's background, not the calling user's.
* MV-cover-letter-studio-006 (MED)  ``_jd_keywords``/``_keyword_coverage`` in
  ``app/routers/cover_letters.py`` do not filter scraper/boilerplate noise
  tokens, so they can crowd real skills entirely out of the 10-item cap.
"""
from __future__ import annotations

import uuid

from app.db import get_connection, new_id


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _seed_base_resume(user_id: str, marker: str, body: str = "") -> None:
    """Seed the user's OWN base (root) résumé version via the real repository —
    mirrors ``test_story_extractor_grounds_on_user_resume`` (test_mv_j_correctness.py)."""
    from app.repositories.resume import ResumeRepository

    text = f"{marker}\n{body}".strip()
    ResumeRepository().create(
        user_id,
        {"raw_text": text, "bullets": [], "contact": {}},
        f"hash-{marker.lower()}",
    )


def _seed_job(user_id: str, description: str, title: str = "Senior Backend Engineer") -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (job_id, user_id, title, "Acme", "Sydney NSW",
                 True, description, "[]", "remoteok", f"https://example.com/{job_id}"),
            )
        conn.commit()
    return job_id


# --------------------------------------------------------------------------- #
# NF-final-B-001 — CoverLetterAgent must ground on the caller's OWN résumé
# --------------------------------------------------------------------------- #
def test_cover_letter_agent_grounds_on_user_resume_not_operator_pdf(test_user_id):
    """The prompt CoverLetterAgent sends the LLM must contain the calling
    user's own résumé marker and must NEVER contain the operator's real
    former-employer names (ANZ / Telstra) — those only appear in the bundled
    ``assets/resume/Vik_Resume_Final.pdf`` operator PDF, never in a user's own
    seeded résumé."""
    from app.agents.cover_letter_agent import CoverLetterAgent

    marker = "ZZUSERMARKERCOVER01"
    _seed_base_resume(
        test_user_id, marker,
        "Senior Python engineer with 6 years building cloud-native backend systems.",
    )

    captured: dict[str, str] = {}

    class _FakeLLM:
        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            captured.setdefault("user", user)
            # Deliberately malformed (1 paragraph, no CTA) so the structural
            # gate rejects it after every retry -- we only need the CAPTURED
            # prompt text, not a successfully stored letter.
            return {"hook_reason": "", "body": "Thin single-line body with no call to action."}

    class _StubJobs:
        def get_by_id(self, job_id, user_id):  # noqa: ANN001
            return {
                "id": job_id,
                "title": "Senior Backend Engineer",
                "company": "Acme Corp",
                "description": "We are hiring a backend engineer with Python and cloud experience.",
            }

    class _StubUsers:
        def get_by_id(self, user_id):  # noqa: ANN001
            return {"id": user_id, "name": "MV Tester"}

        def get_target_role(self, user_id):  # noqa: ANN001
            return ""

    agent = CoverLetterAgent(llm=_FakeLLM(), jobs=_StubJobs(), users=_StubUsers())
    try:
        agent.run(test_user_id, "job-mv-nf001")
    except Exception:
        # The malformed FakeLLM output is expected to be rejected by the
        # FabricationGuard / structural gate after every retry -- irrelevant
        # here since the prompt was already captured on the FIRST LLM call,
        # before any of that downstream adjudication runs.
        pass

    prompt = captured.get("user", "")
    assert prompt, "CoverLetterAgent never reached the LLM call"
    assert marker in prompt, (
        "cover letter agent did not ground its prompt on the user's own resume: "
        f"marker {marker!r} absent from captured prompt"
    )
    assert "ANZ" not in prompt, (
        "cover letter agent leaked the OPERATOR's bundled resume (ANZ) into a "
        "prompt built for a different user"
    )
    assert "Telstra" not in prompt, (
        "cover letter agent leaked the OPERATOR's bundled resume (Telstra) into "
        "a prompt built for a different user"
    )


# --------------------------------------------------------------------------- #
# app.services.resume_grounding — new shared helper (does not exist pre-fix)
# --------------------------------------------------------------------------- #
def test_resolve_user_resume_text_uses_own_base_when_present(test_user_id):
    from app.services.resume_grounding import resolve_user_resume_text

    marker = "ZZRESOLVETEXTMARKER01"
    _seed_base_resume(test_user_id, marker, "Some grounded content unique to this user.")

    text = resolve_user_resume_text(test_user_id)
    assert marker in text, "resolve_user_resume_text did not return the user's own base resume"
    assert "ANZ" not in text
    assert "Telstra" not in text


def test_resolve_user_resume_text_falls_back_to_bundled_when_no_base():
    """A user with NO résumé on file (fresh id, nothing seeded) falls back to
    the bundled operator PDF -- identical, sanctioned no-resume behaviour."""
    from app.agents.fit_scorer import get_base_resume_path
    from app.services.resume_grounding import resolve_user_resume_text
    from app.services.resume_parser import parse_resume_pdf

    fresh_user_id = str(uuid.uuid4())
    expected = parse_resume_pdf(get_base_resume_path())["raw_text"]
    text = resolve_user_resume_text(fresh_user_id)
    assert text == expected


def test_resolve_user_resume_contact_returns_empty_dict_not_operator_contact(test_user_id):
    """A user who HAS a base résumé but left its contact block empty must get
    back {} -- NEVER silently fall through to the operator's real phone/email/
    LinkedIn (the cross-account PII leak this finding is about)."""
    from app.services.resume_grounding import resolve_user_resume_contact

    marker = "ZZRESOLVECONTACTMARKER01"
    _seed_base_resume(test_user_id, marker, "Contact-less resume body.")

    contact = resolve_user_resume_contact(test_user_id)
    assert contact == {}, (
        f"expected {{}} for a user whose own resume has no contact block, got {contact!r} "
        "(this must never be the operator's contact PII)"
    )


def test_resolve_user_resume_contact_falls_back_to_bundled_when_no_base():
    from app.agents.fit_scorer import get_base_resume_path
    from app.services.resume_grounding import resolve_user_resume_contact
    from app.services.resume_parser import parse_resume_pdf

    fresh_user_id = str(uuid.uuid4())
    expected = parse_resume_pdf(get_base_resume_path())["contact"]
    contact = resolve_user_resume_contact(fresh_user_id)
    assert contact == expected


# --------------------------------------------------------------------------- #
# NF-final-B-002 — fit scoring / job insights must reflect the CALLER's résumé
# --------------------------------------------------------------------------- #
def test_job_insights_reflect_user_resume_not_operator(client, auth_headers, test_user_id):
    """Seed the user's own base résumé with distinctive skills absent from the
    operator's bundled PDF; a job whose description features those skills (and
    also namedrops the operator's real former employers, Telstra/ANZ, as a
    trap) must show the USER's skills as matched -- never the operator's."""
    _seed_base_resume(
        test_user_id, "ZZUSERSKILLSMARKER02",
        "Senior engineer with production Elixir, Erlang and Cassandra experience "
        "building distributed systems.",
    )
    jd = (
        "We are hiring a Senior Backend Engineer with deep production experience in "
        "Elixir, Erlang and Cassandra at scale. Prior experience at Telstra or ANZ "
        "is highly regarded. You will design distributed systems and mentor a team."
    )
    job_id = _seed_job(test_user_id, jd)

    resp = client.get(f"/jobs/{job_id}/insights", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    matched = {kw.lower() for kw in resp.json()["matchedSkills"]}

    assert matched & {"elixir", "erlang", "cassandra"}, (
        "job insights did not reflect the calling user's own resume skills "
        f"(matchedSkills={matched!r}) -- still scoring against the fixed operator resume"
    )
    assert "telstra" not in matched, (
        "job insights matched 'telstra' -- a token from the OPERATOR's own resume "
        "employment history, not this user's -- cross-account leak"
    )


# --------------------------------------------------------------------------- #
# MV-cover-letter-studio-006 — JD keyword coverage must drop scraper noise
# --------------------------------------------------------------------------- #
def test_keyword_coverage_drops_boilerplate_and_surfaces_buried_skills():
    """A garbage JD burying real skills after 10 scraper/boilerplate tokens:
    the 10-item-capped coverage panel must show the real skills, never the
    boilerplate chips (MV-cover-letter-studio-006)."""
    from app.routers.cover_letters import _keyword_coverage

    # Exactly 10 distinct boilerplate/scraper-noise tokens (ledger-named:
    # details, visit, Anti-scrape, notice, tag, Required, skills; plus 3 more
    # from the same conservative non-skill lexicon: scrape, detail, click)
    # BEFORE the 4 real skills -- guaranteed to crowd them out of a [:10] cap
    # with no ranking in place.
    jd = (
        "details visit notice tag Required skills Anti-scrape scrape detail click "
        "Kubernetes Docker Terraform PostgreSQL"
    )
    coverage = _keyword_coverage("", {"description": jd})
    keywords_lower = {item["keyword"].lower() for item in coverage["items"]}

    for boiler in ("details", "visit", "anti-scrape", "notice", "tag", "required", "skills"):
        assert boiler not in keywords_lower, (
            f"boilerplate/scraper token {boiler!r} leaked into JD keyword coverage: "
            f"{sorted(keywords_lower)}"
        )
    for skill in ("kubernetes", "docker", "terraform", "postgresql"):
        assert skill in keywords_lower, (
            f"real skill {skill!r} was crowded out of the 10-item keyword coverage cap "
            f"by boilerplate: {sorted(keywords_lower)}"
        )
