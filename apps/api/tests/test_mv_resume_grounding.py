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
* NF-final-B (5th leaking path, HIGH)  ``GET /resumes/{id}/download`` serves
  the OPERATOR's bundled PDF verbatim for a user's OWN base resume whenever
  its ``formatHash`` matches no bundled asset (always true for a JSON/upload-
  ingested resume) — ``services/resume_pdf.py::resolve_original_pdf`` falls
  back to ``get_base_resume_path()`` and ``routers/resumes.py::download_resume``
  streams that file's raw bytes for a base (parentless) resume.
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
    for operator_marker in (
        "ANZ",
        "Telstra",
        "DESHPANDE",
        "+61 433 224 556",
        "sarkar.vikram@gmail.com",
        "Australian Taxation Office",
    ):
        assert operator_marker not in prompt, (
            f"cover letter agent leaked the OPERATOR's bundled resume ({operator_marker}) "
            "into a prompt built for a different user"
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
    for operator_marker in (
        "ANZ",
        "Telstra",
        "DESHPANDE",
        "+61 433 224 556",
        "sarkar.vikram@gmail.com",
        "Australian Taxation Office",
    ):
        assert operator_marker not in text


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


# --------------------------------------------------------------------------- #
# NF-final-B (5th leaking path, HIGH) — resume PDF download must serve the
# user's OWN uploaded/ingested content, never the operator's bundled PDF.
# --------------------------------------------------------------------------- #
def test_download_resume_serves_users_own_content_not_operator_pdf(client, auth_headers):
    """A base resume ingested via POST /resumes gets a formatHash that never
    matches a bundled asset on disk (the operator's real PDF) --
    ``resolve_original_pdf`` falls back to the bundled operator PDF and
    ``download_resume`` streams it verbatim for a base (parentless) resume.
    The downloaded PDF must contain the calling user's OWN marker/content and
    must NEVER contain the operator's real name, former employers or phone
    number."""
    import io

    import pdfplumber

    marker = "ZZUSERMARKERDOWNLOAD07"
    raw_text = (
        f"{marker}\n"
        "Senior Rust engineer specializing in embedded systems and real-time "
        "control software. Built distributed telemetry pipelines processing "
        "500k events per second across a 40-node cluster. Led a 6-engineer "
        "team delivering a safety-critical firmware platform."
    )
    create = client.post(
        "/resumes",
        json={"label": "Mine", "raw_text": raw_text},
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    resume_id = create.json()["id"]

    resp = client.get(f"/resumes/{resume_id}/download", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF"), "download did not return a PDF"

    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert marker in text, (
        "downloaded resume PDF did not contain the user's own ingested content "
        f"(marker {marker!r} absent) -- served bytes:\n{text[:300]!r}"
    )
    for operator_marker in (
        "ANZ",
        "Telstra",
        "DESHPANDE",
        "+61 433 224 556",
        "sarkar.vikram@gmail.com",
        "Australian Taxation Office",
    ):
        assert operator_marker not in text, (
            f"downloaded resume PDF leaked the OPERATOR's bundled PDF content "
            f"({operator_marker}) for a user's OWN base resume"
        )


# --------------------------------------------------------------------------- #
# Production contract (fix/mv-resume-grounding) — OUTBOUND paths REFUSE (422)
# for an authed user with NO résumé of their own; the bundled operator PDF is
# NEVER emitted into a third-party-visible artifact, and NEVER auto-seeded as
# that user's own base résumé.
# --------------------------------------------------------------------------- #

_OPERATOR_PII_MARKERS = (
    "DESHPANDE",
    "+61 433 224 556",
    "sarkar.vikram@gmail.com",
    "Australian Taxation Office",
    "ANZ",
    "Telstra",
)


def _register_fresh_user(client) -> tuple[str, dict[str, str]]:
    """Register + log in a brand-new user who has seeded NOTHING — genuinely
    no résumé of their own on file. Never use ``seed_own_resume``/``auth_headers``
    for these tests: the whole point is a user with NO base résumé."""
    email = f"mv-noresume-{uuid.uuid4().hex[:10]}@example.com"
    password = "Sup3rSecret"
    reg = client.post("/auth/register", json={"email": email, "password": password})
    assert reg.status_code == 201, reg.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json()["id"], headers


def test_no_resume_user_cover_letter_refused_no_operator_pii(client):
    """A fresh authed user with NO résumé of their own gets an honest 422 on
    cover-letter generation, never the bundled operator PDF grounding it —
    and the operator's real PII never appears anywhere in the response."""
    user_id, headers = _register_fresh_user(client)
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=headers,
    )
    assert run.status_code == 202, run.text
    job = client.get("/jobs", headers=headers).json()[0]

    resp = client.post(
        "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert "Add your resume" in resp.json()["detail"]
    for marker in _OPERATOR_PII_MARKERS:
        assert marker not in resp.text, (
            f"operator PII ({marker!r}) leaked into the 422 response body: {resp.text!r}"
        )


def test_no_resume_user_email_draft_refused(client):
    """A fresh authed user with NO résumé of their own gets an honest
    422/refusal on an email draft_reply — never the operator's résumé grounding
    it, and no operator PII in the response body."""
    user_id, headers = _register_fresh_user(client)
    draft = client.post(
        "/emails/draft",
        json={"subject": "Recruiter outreach", "body": "Are you open to new roles?"},
        headers=headers,
    )
    assert draft.status_code == 201, draft.text
    thread_id = draft.json()["id"]

    resp = client.post(
        "/agents/email/run",
        json={"mode": "draft_reply", "thread_id": thread_id},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "Add your resume" in resp.json()["detail"]
    for marker in _OPERATOR_PII_MARKERS:
        assert marker not in resp.text, (
            f"operator PII ({marker!r}) leaked into the 422 response body: {resp.text!r}"
        )


def test_no_resume_user_tailor_refused_and_no_base_created(client):
    """A fresh authed user with NO résumé of their own gets an honest 422 on
    tailoring, and — critically — the bundled operator PDF is NEVER seeded as
    this user's own base résumé as a side effect of the refused attempt
    (NF-final-B-005): GET /resumes must still return []."""
    user_id, headers = _register_fresh_user(client)
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=headers,
    )
    assert run.status_code == 202, run.text
    job = client.get("/jobs", headers=headers).json()[0]

    resp = client.post(
        "/agents/tailor/run", json={"job_id": job["id"]}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert "Add your resume before tailoring" in resp.json()["detail"]

    resumes = client.get("/resumes", headers=headers).json()
    assert resumes == [], (
        "a refused tailor run seeded the operator PDF as this user's own base "
        f"resume as a side effect: {resumes!r}"
    )


# --------------------------------------------------------------------------- #
# NF-final-B-007 (MED) — INTERNAL read-only analytics (job-insights + cover-
# letter voice/evidence corpus) must NOT fall back to the operator résumé for a
# caller with no résumé of their own. They degrade to an honest empty-state
# (HTTP 200 + a ``needsResume`` prompt), never a fit/voice computed against the
# bundled operator résumé and labelled as the user's own.
# --------------------------------------------------------------------------- #
def test_no_resume_user_job_insights_empty_state_not_operator(client):
    """A no-résumé user's GET /jobs/{id}/insights is an honest empty-state — not
    a fit scored against the operator résumé."""
    user_id, headers = _register_fresh_user(client)
    job_id = _seed_job(
        user_id, "Python, Django, PostgreSQL and Kubernetes backend role.",
    )
    resp = client.get(f"/jobs/{job_id}/insights", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needsResume"] is True, body
    assert body["scored"] is False, body
    assert body["matchedSkills"] == [] and body["skillsMatched"] == 0, body
    assert body["overall"] == 0, body
    # No operator skills/PII presented as this user's own fit.
    for marker in _OPERATOR_PII_MARKERS:
        assert marker not in resp.text, (
            f"operator PII ({marker!r}) surfaced in a no-résumé user's insights"
        )


def test_no_resume_user_cover_letter_insights_shows_needs_resume(client):
    """The cover-letter studio voice/evidence corpus must not fall back to the
    operator résumé once the caller has no résumé of their own — the panel shows
    ``needsResume`` and grounds on NO operator content."""
    from conftest import FIXTURE_LLM_RESUME_TEXT, seed_own_resume

    from app.repositories.cover_letter import CoverLetterRepository
    from app.repositories.resume import ResumeRepository

    user_id, headers = _register_fresh_user(client)
    # Give the user a real base résumé so a letter can legitimately exist …
    seed_own_resume(client, headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
    job_id = _seed_job(user_id, "Python and PostgreSQL backend role.")
    base = ResumeRepository().get_base(user_id)
    letter = CoverLetterRepository().create(
        user_id, job_id, base["id"],
        "Dear Hiring Team,\n\nI led delivery on a payments platform.\n\nSincerely,\nJordan",
    )
    # … then the user removes their résumé grounding (row stays, no grounding
    # text): the panel must NOT silently fall back to the operator résumé.
    ResumeRepository().update_sections(base["id"], user_id, {}, base["formatHash"])

    resp = client.get(f"/cover-letters/{letter['id']}/insights", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needsResume"] is True, body
    for marker in _OPERATOR_PII_MARKERS:
        assert marker not in resp.text, (
            f"operator PII ({marker!r}) surfaced in a no-résumé user's cover-letter insights"
        )
