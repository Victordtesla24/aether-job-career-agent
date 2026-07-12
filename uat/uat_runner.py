#!/usr/bin/env python3
"""Independent real-world UAT harness for Aether Career Agent.

Drives the DEPLOYED production app (https://5cb5f0620.abacusai.cloud) exactly
the way the target user (a Melbourne senior BA/PO/TPM) would to reach the
product's core promise: autonomously discover best-fit jobs, tailor evidence-
grounded applications, and apply — maximizing interview conversion odds.

Completely independent of the repo's unit/e2e suites: scenarios assert user-
visible OUTCOMES (real data, real state changes), not component rendering.

Usage:
    python3 uat/uat_runner.py            # full run, report to uat/reports/
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys
import time

import requests
from playwright.sync_api import sync_playwright

BASE = "https://5cb5f0620.abacusai.cloud"
API = f"{BASE}/api"
CREDS = {"email": "demo@aether.dev", "password": "AetherDemo1"}
REPORT_DIR = pathlib.Path(__file__).parent / "reports"
SHOT_DIR = REPORT_DIR / "evidence"

# Role families the user targets — interview conversion depends on applying
# ONLY to jobs in these families.
TARGET_ROLE_RE = re.compile(
    r"business analyst|product owner|product manager|program|project|delivery"
    r"|technical lead|tech lead|scrum|agile|transformation|iteration|implementation"
    r"|change|pmo|account manager|engagement|governance|grc",
    re.I,
)

findings: list[dict] = []


def record(scenario: str, step: str, status: str, detail: str, severity: str = "medium",
           evidence: str | None = None) -> None:
    findings.append({
        "scenario": scenario, "step": step, "status": status,
        "severity": severity if status != "pass" else "",
        "detail": detail, "evidence": evidence or "",
    })
    mark = {"pass": "✓", "defect": "✗", "gap": "△", "info": "·"}.get(status, "?")
    print(f"  {mark} [{scenario}] {step}: {detail[:120]}", flush=True)


def api(token: str, method: str, path: str, **kw):
    r = requests.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {token}"},
                         timeout=kw.pop("timeout", 60), **kw)
    return r


def main() -> int:
    REPORT_DIR.mkdir(exist_ok=True)
    SHOT_DIR.mkdir(exist_ok=True)
    started = datetime.datetime.now()

    # ---- API session ------------------------------------------------------
    resp = requests.post(f"{API}/auth/login", json=CREDS, timeout=30)
    if resp.status_code != 200:
        record("UAT-00", "login", "defect", f"API login failed: HTTP {resp.status_code}", "critical")
        return finish(started)
    token = resp.json()["access_token"]
    record("UAT-00", "login", "pass", "API login returns bearer token")

    # ======================================================================
    # UAT-01 — Autonomous discovery: agents bring in fresh, real jobs
    # ======================================================================
    before = api(token, "GET", "/jobs").json()
    before_ids = {j["id"] for j in before}
    r = api(token, "POST", "/agents/scout/run",
            json={"query": "senior business analyst, product owner, program manager",
                  "location": "Melbourne VIC"}, timeout=300)
    if r.status_code not in (200, 202):
        record("UAT-01", "scout run", "defect", f"scout run HTTP {r.status_code}: {r.text[:120]}", "critical")
    else:
        record("UAT-01", "scout run", "pass", f"scout accepted (HTTP {r.status_code})")
    time.sleep(5)
    after = api(token, "GET", "/jobs").json()
    new_jobs = [j for j in after if j["id"] not in before_ids]
    record("UAT-01", "fresh jobs", "pass" if after else "defect",
           f"{len(after)} total jobs, {len(new_jobs)} new this run", "high")
    fake_markers = [j for j in after if re.search(r"demo|test corp|acme|lorem", f"{j['company']} {j['title']}", re.I)]
    record("UAT-01", "no fake jobs", "pass" if not fake_markers else "defect",
           "zero demo/test companies" if not fake_markers else f"fake-looking rows: {[j['company'] for j in fake_markers][:3]}",
           "critical")

    r = api(token, "POST", "/agents/fit-scorer/run", json={}, timeout=300)
    scored_payload = r.json() if r.status_code == 200 else {}
    unscored = [j for j in api(token, "GET", "/jobs").json() if j.get("fitScore") is None]
    record("UAT-01", "auto fit-scoring", "pass" if not unscored else "defect",
           f"fit-scorer run: {scored_payload}; unscored jobs remaining: {len(unscored)}", "high")

    # ======================================================================
    # UAT-02 — Best-fit triage: ranking must serve interview conversion
    # ======================================================================
    jobs = api(token, "GET", "/jobs?sort=fitScore").json()
    top10 = jobs[:10]
    relevant = [j for j in top10 if TARGET_ROLE_RE.search(j["title"] or "")]
    record("UAT-02", "top-10 relevance", "pass" if len(relevant) >= 8 else "defect",
           f"{len(relevant)}/10 top-ranked jobs match the user's target role families "
           f"(irrelevant: {[j['title'][:40] for j in top10 if j not in relevant][:3]})", "high")
    au = [j for j in top10 if re.search(r"melbourne|vic|australia|nsw|sydney|act|qld|remote", j.get("location") or "", re.I)]
    record("UAT-02", "top-10 location", "pass" if len(au) >= 7 else "gap",
           f"{len(au)}/10 top jobs are AU/remote for a Melbourne-based user", "medium")
    def _age_days(iso: str) -> int:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days

    stale = [j for j in top10 if j.get("postedAt") and _age_days(j["postedAt"]) > 30]
    record("UAT-02", "freshness", "pass" if len(stale) <= 2 else "gap",
           f"{len(stale)}/10 top jobs are older than 30 days (interview odds decay fast)", "medium")

    # ======================================================================
    # UAT-03 — Insight quality on the #1 job (what convinces the user to apply)
    # ======================================================================
    top = jobs[0]
    ins = api(token, "GET", f"/jobs/{top['id']}/insights").json()
    ok = ins.get("scored") and ins.get("matchedSkills") and len(ins.get("dimensions") or []) == 10 \
        and (ins.get("narrative") or "").strip()
    record("UAT-03", "insights depth", "pass" if ok else "defect",
           f"#1 job '{top['title'][:40]}' insights: scored={ins.get('scored')} "
           f"skills={len(ins.get('matchedSkills') or [])} dims={len(ins.get('dimensions') or [])}", "high")

    # ======================================================================
    # UAT-04 — The core loop in the real UI: tailor → review → apply
    # ======================================================================
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        console_errors: list[str] = []
        pg.on("console", lambda m: console_errors.append(m.text[:150]) if m.type == "error" else None)

        pg.goto(f"{BASE}/login", wait_until="networkidle")
        pg.fill('[name=email]', CREDS["email"])
        pg.fill('[name=password]', CREDS["password"])
        pg.click('[type=submit]')
        try:
            pg.wait_for_url("**/dashboard**", timeout=30000)
            record("UAT-04", "UI login", "pass", "login lands on dashboard")
        except Exception:
            record("UAT-04", "UI login", "defect", f"stuck at {pg.url}", "critical")
            b.close()
            return finish(started)

        pg.goto(f"{BASE}/dashboard/jobs", wait_until="networkidle")
        pg.wait_for_timeout(5000)
        cards = pg.get_by_test_id("job-card")
        if cards.count() == 0:
            record("UAT-04", "job list", "defect", "no job cards rendered", "critical")
        else:
            # Target the best-fit job NOT yet applied to — apply is idempotent,
            # so re-running UAT against an already-applied job proves nothing.
            applied_ids = {a.get("jobId") for a in api(token, "GET", "/applications").json()}
            ranked = api(token, "GET", "/jobs?sort=fitScore").json()
            target_idx = next(
                (i for i, j in enumerate(ranked[: cards.count()]) if j["id"] not in applied_ids), 0)
            record("UAT-04", "target job", "info",
                   f"applying to rank #{target_idx + 1}: {ranked[target_idx]['title'][:50]}")
            cards.nth(target_idx).click()
            pg.wait_for_timeout(2500)
            tailor = pg.get_by_test_id("tailor-resume")
            if not tailor.is_visible():
                record("UAT-04", "tailor CTA", "defect", "Tailor Resume button not visible on selected job", "critical")
            else:
                tailor.click()
                record("UAT-04", "tailoring", "info", "tailor started — waiting for the REAL agent run")
                try:
                    pg.get_by_test_id("apply-step2").wait_for(timeout=180_000)
                    banner = pg.get_by_test_id("apply-step2").inner_text()
                    m = re.search(r"(\d+)\s*changes applied", banner)
                    changes = int(m.group(1)) if m else 0
                    record("UAT-04", "tailor result", "pass" if changes >= 1 else "defect",
                           f"tailored with {changes} changes shown ('{banner[:90]}')", "critical")
                    pg.screenshot(path=str(SHOT_DIR / "uat04_tailored.png"))
                    pg.get_by_test_id("review-apply").click()
                    pg.get_by_test_id("submit-gate").wait_for(timeout=15000)
                    gate_text = pg.get_by_test_id("submit-gate").inner_text()
                    honest = "recorded" in gate_text.lower() and "cannot be undone" not in gate_text.lower()
                    record("UAT-04", "gate honesty", "pass" if honest else "defect",
                           "submit gate states tracking truthfully" if honest else f"gate copy misleading: {gate_text[:120]}",
                           "high")
                    apps_before = {a["id"] for a in api(token, "GET", "/applications").json()}
                    pg.get_by_test_id("submit-confirm").click()
                    pg.get_by_test_id("submitted-state").wait_for(timeout=30000)
                    pg.screenshot(path=str(SHOT_DIR / "uat04_submitted.png"))
                    time.sleep(2)
                    apps_after = api(token, "GET", "/applications").json()
                    new_apps = [a for a in apps_after if a["id"] not in apps_before]
                    record("UAT-04", "application persisted", "pass" if new_apps else "defect",
                           f"{len(new_apps)} new Application row(s) created by the UI flow", "critical",
                           "uat04_submitted.png")
                    tailored_attached = any(a.get("resumeId") for a in new_apps)
                    record("UAT-04", "tailored resume attached", "pass" if tailored_attached else "defect",
                           "application references a resume version" if tailored_attached
                           else "application has no resumeId — tailoring not linked to the application",
                           "high")
                except Exception as exc:
                    pg.screenshot(path=str(SHOT_DIR / "uat04_failed.png"))
                    record("UAT-04", "tailor→apply flow", "defect",
                           f"flow did not complete: {type(exc).__name__} {str(exc)[:120]}", "critical",
                           "uat04_failed.png")

        # ==================================================================
        # UAT-05 — Pipeline visibility: the new application shows in tracker
        # ==================================================================
        pg.goto(f"{BASE}/dashboard/applications", wait_until="networkidle")
        pg.wait_for_timeout(4000)
        body = pg.inner_text("body")
        has_card = "applied" in body.lower() or "submitted" in body.lower()
        pg.screenshot(path=str(SHOT_DIR / "uat05_tracker.png"))
        record("UAT-05", "tracker shows application", "pass" if has_card else "defect",
               "application visible in tracker" if has_card else "tracker does not show the new application",
               "high", "uat05_tracker.png")

        # ==================================================================
        # UAT-06 — Evidence-grounded cover letter + human approval gate
        # ==================================================================
        cl = api(token, "POST", "/agents/cover-letter/run", json={"job_id": top["id"]}, timeout=300)
        if cl.status_code not in (200, 202):
            record("UAT-06", "cover letter generation", "defect",
                   f"HTTP {cl.status_code}: {cl.text[:120]}", "high")
        else:
            record("UAT-06", "cover letter generation", "pass", "real LLM cover letter generated")
            letters = api(token, "GET", "/cover-letters").json()
            if letters:
                lid = letters[0]["id"]
                insights = api(token, "GET", f"/cover-letters/{lid}/insights").json()
                grounded = (insights.get("voice") or {}).get("authenticity", 0)
                record("UAT-06", "evidence grounding", "pass" if grounded >= 60 else "gap",
                       f"letter grounding {grounded}% (claims traced to resume/stories)", "medium")
            pending = api(token, "GET", "/approvals?status=pending").json()
            record("UAT-06", "approval gate", "pass" if pending else "gap",
                   f"{len(pending)} pending approval(s) awaiting the human" if pending
                   else "no approval created for gated cover-letter send", "medium")
            if pending:
                pg.goto(f"{BASE}/dashboard/approvals", wait_until="networkidle")
                pg.wait_for_timeout(4000)
                approvals_body = pg.inner_text("body")
                visible = "approve" in approvals_body.lower()
                record("UAT-06", "approval UI", "pass" if visible else "defect",
                       "pending item actionable in approvals UI" if visible else "approvals UI empty despite pending item",
                       "high")

        # ==================================================================
        # UAT-07 — Fully autonomous pipeline (one click / zero clicks)
        # ==================================================================
        rp = api(token, "POST", "/agents/pipeline/run", json={}, timeout=600)
        runs = api(token, "GET", "/agents/runs").json()[:8]
        failed = [x for x in runs if x.get("status") == "failed"]
        record("UAT-07", "autonomous pipeline", "pass" if rp.status_code in (200, 202) and not failed else "defect",
               f"pipeline HTTP {rp.status_code}; recent runs: "
               + ", ".join(f"{x['agentName']}:{x['status']}" for x in runs[:6]), "high")

        # ==================================================================
        # UAT-08 — Mobile: approve on the go (390×844)
        # ==================================================================
        mb = b.new_page(viewport={"width": 390, "height": 844})
        mb.goto(f"{BASE}/login", wait_until="networkidle")
        mb.fill('[name=email]', CREDS["email"])
        mb.fill('[name=password]', CREDS["password"])
        mb.click('[type=submit]')
        try:
            mb.wait_for_url("**/dashboard**", timeout=30000)
            for route in ("/dashboard", "/dashboard/approvals"):
                mb.goto(BASE + route, wait_until="networkidle")
                mb.wait_for_timeout(3500)
                overflow = mb.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2")
                record("UAT-08", f"mobile {route}", "pass" if not overflow else "defect",
                       "no horizontal overflow" if not overflow else "horizontal overflow on mobile viewport",
                       "medium")
            mb.screenshot(path=str(SHOT_DIR / "uat08_mobile.png"))
        except Exception as exc:
            record("UAT-08", "mobile login", "defect", f"{type(exc).__name__}: {str(exc)[:100]}", "high")

        if console_errors:
            record("UAT-09", "console hygiene", "defect",
                   f"{len(console_errors)} console errors during journeys: {sorted(set(console_errors))[:2]}", "medium")
        else:
            record("UAT-09", "console hygiene", "pass", "zero browser console errors across all journeys")
        b.close()

    return finish(started)


def finish(started) -> int:
    ts = started.strftime("%Y%m%d-%H%M%S")
    defects = [f for f in findings if f["status"] == "defect"]
    gaps = [f for f in findings if f["status"] == "gap"]
    passes = [f for f in findings if f["status"] == "pass"]
    (REPORT_DIR / f"UAT-RESULTS-{ts}.json").write_text(json.dumps(findings, indent=2))

    lines = [
        f"# UAT Report — Aether Career Agent ({started:%Y-%m-%d %H:%M} UTC)",
        "",
        f"Production target: {BASE} · independent real-world journeys",
        f"**Result: {len(passes)} passed · {len(defects)} defects · {len(gaps)} gaps**",
        "",
        "| Scenario | Step | Status | Severity | Detail |",
        "|---|---|---|---|---|",
    ]
    for f in findings:
        lines.append(f"| {f['scenario']} | {f['step']} | {f['status'].upper()} | {f['severity']} | {f['detail'][:140]} |")
    (REPORT_DIR / f"UAT-REPORT-{ts}.md").write_text("\n".join(lines) + "\n")
    print(f"\nUAT COMPLETE: {len(passes)} passed, {len(defects)} defects, {len(gaps)} gaps")
    print(f"report: uat/reports/UAT-REPORT-{ts}.md")
    return 1 if defects else 0


if __name__ == "__main__":
    sys.exit(main())
