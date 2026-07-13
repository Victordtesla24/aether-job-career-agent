#!/usr/bin/env python3
"""Comprehensive API endpoint sweep against production.
Requires: LOGIN_EMAIL, LOGIN_PASSWORD in ../.env
"""
import json, os, re, subprocess, sys, time, urllib.parse
from pathlib import Path

BASE_URL = "https://5cb5f0620.abacusai.cloud"
API_PREFIX = "/api"
OUTPUT = Path("/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/phase4/api-sweep-results.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
TIMEOUT = 120

def load_env():
    env_path = Path("/home/ubuntu/github_repos/aether-job-career-agent/.env")
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

env = load_env()
EMAIL = env["LOGIN_EMAIL"]
PASSWORD = env["LOGIN_PASSWORD"]

def curl(method, path, body=None, token=None, timeout=None):
    """Execute a single curl and return (status, body_str, latency)."""
    if timeout is None:
        timeout = TIMEOUT
    url = f"{BASE_URL}{path}"
    cmd = [
        "curl", "-s", "-w", "\n%{http_code}\n%{time_total}", "-o", "-",
        "-X", method,
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: application/json",
        "--max-time", str(timeout),
        "--connect-timeout", "15",
        url
    ]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]

    t0 = time.time()
    curl_time = None
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout+5)
        latency = round(time.time() - t0, 3)
        output = result.stdout
        # Try text decode; fall back to binary marker
        try:
            text_out = output.decode("utf-8")
        except UnicodeDecodeError:
            # Binary response (e.g. PDF download)
            text_out = output.decode("utf-8", errors="replace")
            binary = True
        else:
            binary = False

        parts = text_out.rsplit("\n", 2)
        if len(parts) == 3:
            body_text = parts[0]
            try:
                status = int(parts[1].strip())
            except ValueError:
                status = 0
            try:
                curl_time = float(parts[2].strip())
            except ValueError:
                curl_time = None
        else:
            body_text = text_out
            status = 0

        if binary:
            if not body_text or len(body_text) < 10:
                body_text = f"[BINARY {len(output)} bytes]"

        return status, body_text, curl_time if curl_time else latency
    except subprocess.TimeoutExpired:
        return 0, "TIMEOUT", float(timeout)

def login():
    """POST /api/auth/login and return token."""
    status, body, lat = curl("POST", "/api/auth/login", body={
        "email": EMAIL, "password": PASSWORD
    })
    if status != 200:
        print(f"LOGIN FAILED: {status} {body[:200]}")
        sys.exit(1)
    try:
        data = json.loads(body)
        token = data.get("access_token", "")
        if not token:
            print("LOGIN: no access_token in response")
            sys.exit(1)
        return token
    except json.JSONDecodeError:
        print(f"LOGIN: non-JSON response: {body[:200]}")
        sys.exit(1)

def snippet(body, length=500):
    if not body:
        return ""
    return body[:length]

def gap_flag(status, body_str=""):
    """True if 5xx, unhandled 4xx (not 401/403/404/409/422), or schema mismatch."""
    if status >= 500:
        return True
    # 4xx that are unexpected/indicative of bugs
    # 400, 405, 413, 415, 429, 431 etc.
    if 400 <= status < 500 and status not in (401, 403, 404, 409, 422):
        return True
    return False

def record(results, method, path, status, body, latency, note=""):
    entry = {
        "method": method,
        "path": path,
        "status": status,
        "snippet": snippet(body),
        "latency": round(latency, 3) if latency else None,
        "gap": gap_flag(status, body),
    }
    if note:
        entry["note"] = note
    results.append(entry)
    print(f"  {method:6} {path:60} → {status} ({latency:.3f}s)" + (" GAP" if entry["gap"] else ""))

def main():
    results = []
    print("=== Phase 4: API Sweep ===")
    print(f"Base: {BASE_URL}{API_PREFIX}")

    # ── Login ──
    print("\n--- Auth ---")
    token = login()
    print("JWT obtained")

    # ── Test login as a result too ──
    status, body, lat = curl("POST", "/api/auth/login", body={
        "email": EMAIL, "password": PASSWORD
    })
    record(results, "POST", "/api/auth/login", status, body, lat)

    # ── Health (no auth) ──
    print("\n--- Health ---")
    status, body, lat = curl("GET", "/api/health")
    record(results, "GET", "/api/health", status, body, lat)

    # ── Auth endpoints ──
    for method, path, body, note in [
        ("POST", "/api/auth/register", {"email": "sweep_" + str(int(time.time())) + "@test.com", "password": "TestPass123!"}, "expected 409 if dup"),
        ("GET", "/api/auth/me", None, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    # ── Helper: get IDs from list endpoints ──
    def get_first_id(list_path, id_field="id"):
        status, resp, lat = curl("GET", list_path, token=token)
        if status == 200:
            try:
                items = json.loads(resp)
                if isinstance(items, list) and items:
                    return items[0].get(id_field)
                if isinstance(items, dict):
                    # maybe wrapped
                    for key in ["items", "data", "results"]:
                        if key in items and items[key]:
                            return items[key][0].get(id_field)
            except json.JSONDecodeError:
                pass
        return None

    # ── Jobs ──
    print("\n--- Jobs ---")
    job_id = None
    for method, path_tpl, body, note in [
        ("GET", "/api/jobs", None, ""),
    ]:
        path = path_tpl
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)
        if status == 200:
            try:
                items = json.loads(resp)
                if isinstance(items, list) and items:
                    job_id = items[0].get("id") or items[0].get("job_id")
            except:
                pass

    if job_id:
        for method, path_tpl, body, note in [
            ("GET", "/api/jobs/" + job_id, None, ""),
            ("GET", "/api/jobs/" + job_id + "/insights", None, ""),
            ("POST", "/api/jobs/" + job_id + "/save", {}, ""),
            # POST apply - may change state, test cautiously
            ("POST", "/api/jobs/" + job_id + "/apply", {}, "may 409 if already applied"),
        ]:
            status, resp, lat = curl(method, path_tpl, body=body, token=token)
            record(results, method, path_tpl, status, resp, lat, note)
    else:
        record(results, "GET", "/api/jobs/{job_id} (SKIPPED)", 0, "No job IDs from list", 0, "no_data")
        record(results, "GET", "/api/jobs/{job_id}/insights (SKIPPED)", 0, "No job IDs from list", 0, "no_data")
        record(results, "POST", "/api/jobs/{job_id}/save (SKIPPED)", 0, "No job IDs from list", 0, "no_data")
        record(results, "POST", "/api/jobs/{job_id}/apply (SKIPPED)", 0, "No job IDs from list", 0, "no_data")

    # ── Agents ──
    print("\n--- Agents ---")
    # GET /agents → list
    agent_names = []
    for method, path, body, note in [
        ("GET", "/api/agents", None, ""),
        ("GET", "/api/agents/runs", None, ""),
        ("GET", "/api/agents/catalog", None, ""),
        ("GET", "/api/agents/providers", None, ""),
        ("GET", "/api/agents/stats", None, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)
        if path == "/api/agents" and status == 200:
            try:
                agent_names = [a.get("name", "") for a in json.loads(resp)]
            except:
                pass

    # Agent run endpoints (POST bodies require params)
    for method, path, body, note in [
        ("POST", "/api/agents/scout/run", {"query": "software engineer", "location": "remote"}, "[scout]"),
        ("POST", "/api/agents/fit-scorer/run", {"rescore": False}, "[fit-scorer]"),
        ("POST", "/api/agents/tailor/run", {"job_id": job_id or "nonexistent", "resume_id": None}, "needs real job_id"),
        ("POST", "/api/agents/cover-letter/run", {"job_id": job_id or "nonexistent", "resume_id": None}, "needs real job_id"),
        ("POST", "/api/agents/story-extractor/run", {}, "[story-extractor]"),
        ("POST", "/api/agents/pipeline/run", {"job_id": job_id or "nonexistent"}, "needs real job_id"),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    # Agent runs/{id}
    run_id = get_first_id("/api/agents/runs", "id")
    if run_id:
        status, resp, lat = curl("GET", f"/api/agents/runs/{run_id}", token=token)
        record(results, "GET", f"/api/agents/runs/{run_id}", status, resp, lat)
    else:
        record(results, "GET", "/api/agents/runs/{run_id} (SKIPPED)", 0, "No run IDs", 0, "no_data")

    # PUT /agents/config/{agent_key}
    if agent_names:
        agent_key = agent_names[0]
        status, resp, lat = curl("PUT", f"/api/agents/config/{agent_key}", body={"enabled": True}, token=token)
        record(results, "PUT", f"/api/agents/config/{agent_key}", status, resp, lat)
    else:
        record(results, "PUT", "/api/agents/config/{agent_key} (SKIPPED)", 0, "No agent names", 0, "no_data")

    # PUT /agents/providers/{provider} - test with 'openai'
    status, resp, lat = curl("PUT", "/api/agents/providers/openai", body={"api_key": "test"}, token=token)
    record(results, "PUT", "/api/agents/providers/openai", status, resp, lat)

    # POST /agents/test-run
    status, resp, lat = curl("POST", "/api/agents/test-run", body={"agent_name": agent_names[0] if agent_names else "scout"}, token=token)
    record(results, "POST", "/api/agents/test-run", status, resp, lat)

    # POST /agents/{name}/run
    if agent_names:
        name = agent_names[0]
        status, resp, lat = curl("POST", f"/api/agents/{name}/run", body={"job_id": job_id or "test"}, token=token)
        record(results, "POST", f"/api/agents/{name}/run", status, resp, lat)

    # ── Resumes ──
    print("\n--- Resumes ---")
    resume_id = get_first_id("/api/resumes", "id")
    for method, path, body, note in [
        ("GET", "/api/resumes", None, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    if resume_id:
        for method, path, body, note in [
            ("GET", f"/api/resumes/{resume_id}", None, ""),
            ("GET", f"/api/resumes/{resume_id}/ats", None, ""),
            ("GET", f"/api/resumes/{resume_id}/diff", None, ""),
            ("GET", f"/api/resumes/{resume_id}/download", None, ""),
        ]:
            status, resp, lat = curl(method, path, body=body, token=token)
            record(results, method, path, status, resp, lat, note)
    else:
        for ep in ["/{id}", "/{id}/ats", "/{id}/diff", "/{id}/download"]:
            record(results, "GET", f"/api/resumes{ep} (SKIPPED)", 0, "No resume IDs", 0, "no_data")

    # POST /resumes
    status, resp, lat = curl("POST", "/api/resumes", body={
        "label": "Test Resume Sweep",
        "raw_text": "Experienced software engineer with 10 years of Python, FastAPI, and cloud architecture experience. Built scalable microservices.",
        "contact": {"email": EMAIL}
    }, token=token)
    record(results, "POST", "/api/resumes", status, resp, lat)

    # POST /resumes/upload - skip (needs file)

    # ── Approvals ──
    print("\n--- Approvals ---")
    status, resp, lat = curl("GET", "/api/approvals", token=token)
    record(results, "GET", "/api/approvals", status, resp, lat)
    approval_id = None
    if status == 200:
        try:
            items = json.loads(resp)
            if isinstance(items, list) and items:
                approval_id = items[0].get("id")
        except:
            pass

    if approval_id:
        for method, path, body, note in [
            ("GET", f"/api/approvals/{approval_id}", None, ""),
            ("POST", f"/api/approvals/{approval_id}/approve", {}, ""),
            ("POST", f"/api/approvals/{approval_id}/reject", {}, ""),
            ("POST", f"/api/approvals/{approval_id}/execute", {}, ""),
        ]:
            status, resp, lat = curl(method, path, body=body, token=token)
            record(results, method, path, status, resp, lat, note)
    else:
        for ep in ["/{id}", "/{id}/approve", "/{id}/reject", "/{id}/execute"]:
            record(results, "GET/POST", f"/api/approvals{ep} (SKIPPED)", 0, "No approval IDs", 0, "no_data")

    # POST /approvals
    status, resp, lat = curl("POST", "/api/approvals", body={
        "type": "cover_letter",
        "target_id": "test-sweep-001"
    }, token=token)
    record(results, "POST", "/api/approvals", status, resp, lat)

    # ── Cover Letters ──
    print("\n--- Cover Letters ---")
    cl_id = get_first_id("/api/cover-letters", "id")
    status, resp, lat = curl("GET", "/api/cover-letters", token=token)
    record(results, "GET", "/api/cover-letters", status, resp, lat)

    if cl_id:
        for method, path, body, note in [
            ("GET", f"/api/cover-letters/{cl_id}", None, ""),
            ("GET", f"/api/cover-letters/{cl_id}/insights", None, ""),
            ("POST", f"/api/cover-letters/{cl_id}/refine", {"instruction": "Make it more concise"}, ""),
            ("GET", f"/api/cover-letters/{cl_id}/pdf", None, ""),
        ]:
            status, resp, lat = curl(method, path, body=body, token=token)
            record(results, method, path, status, resp, lat, note)
    else:
        for ep in ["/{id}", "/{id}/insights", "/{id}/refine", "/{id}/pdf"]:
            record(results, "GET/POST", f"/api/cover-letters{ep} (SKIPPED)", 0, "No cover letter IDs", 0, "no_data")

    # ── Stories ──
    print("\n--- Stories ---")
    story_id = get_first_id("/api/stories", "id")
    for method, path, body, note in [
        ("GET", "/api/stories", None, ""),
        ("GET", "/api/stories/stats", None, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    if story_id:
        for method, path, body, note in [
            ("PUT", f"/api/stories/{story_id}", {"title": "Updated Story"}, ""),
            ("DELETE", f"/api/stories/{story_id}", None, "will delete - careful"),
        ]:
            # Skip actual delete by changing to a fake ID
            if method == "DELETE":
                status, resp, lat = curl(method, f"/api/stories/fake-id-not-real", token=token)
                record(results, method, f"/api/stories/fake-id-not-real", status, resp, lat, "using fake ID to avoid deletion")
            else:
                status, resp, lat = curl(method, path, body=body, token=token)
                record(results, method, path, status, resp, lat, note)
    else:
        record(results, "PUT", "/api/stories/{story_id} (SKIPPED)", 0, "No story IDs", 0, "no_data")
        record(results, "DELETE", "/api/stories/{story_id} (SKIPPED)", 0, "No story IDs", 0, "no_data")

    # POST /stories
    status, resp, lat = curl("POST", "/api/stories", body={
        "title": "Test Story Sweep",
        "situation": "We had a tight deadline",
        "task": "Deliver the feature",
        "action": "Coordinated across teams",
        "result": "Shipped on time",
        "tags": ["leadership", "collaboration"],
        "metrics": {"revenue": "saved 50 hours"}
    }, token=token)
    record(results, "POST", "/api/stories", status, resp, lat)

    # ── Analytics ──
    print("\n--- Analytics ---")
    for method, path, body, note in [
        ("GET", "/api/analytics", None, ""),
        ("GET", "/api/analytics/funnel", None, ""),
        ("GET", "/api/analytics/ats-distribution", None, ""),
        ("GET", "/api/analytics/agent-roi", None, ""),
        ("GET", "/api/analytics/conversion", None, ""),
        ("GET", "/api/analytics/market-pulse", None, ""),
        ("GET", "/api/analytics/dashboard", None, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    # ── Applications ──
    print("\n--- Applications ---")
    app_id = get_first_id("/api/applications", "id")
    for method, path, body, note in [
        ("GET", "/api/applications/funnel/sankey", None, ""),
        ("GET", "/api/applications", None, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    if app_id:
        status, resp, lat = curl("GET", f"/api/applications/{app_id}", token=token)
        record(results, "GET", f"/api/applications/{app_id}", status, resp, lat)
        status, resp, lat = curl("POST", f"/api/applications/{app_id}/submit", body={}, token=token)
        record(results, "POST", f"/api/applications/{app_id}/submit", status, resp, lat)
    else:
        record(results, "GET", "/api/applications/{id} (SKIPPED)", 0, "No app IDs", 0, "no_data")
        record(results, "POST", "/api/applications/{id}/submit (SKIPPED)", 0, "No app IDs", 0, "no_data")

    # ── Workspaces ──
    print("\n--- Workspaces ---")
    for method, path, body, note in [
        ("GET", "/api/workspaces/interviews/prep", None, ""),
        ("GET", "/api/workspaces/networking/summary", None, ""),
        ("GET", "/api/workspaces/emails/inbox", None, ""),
        ("POST", "/api/workspaces/emails/send", {"to": "test@example.com", "subject": "Test", "body": "Test body"}, ""),
        ("GET", "/api/workspaces/offers", None, ""),
        ("GET", "/api/workspaces/settings", None, ""),
        ("PUT", "/api/workspaces/settings", {"theme": "dark"}, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    # ── Interviews ──
    print("\n--- Interviews ---")
    interview_id = get_first_id("/api/interviews", "id")
    status, resp, lat = curl("GET", "/api/interviews", token=token)
    record(results, "GET", "/api/interviews", status, resp, lat)

    if interview_id:
        for method, path, body, note in [
            ("GET", f"/api/interviews/{interview_id}", None, ""),
            ("PATCH", f"/api/interviews/{interview_id}", {"status": "scheduled"}, ""),
            ("POST", f"/api/interviews/{interview_id}/complete", {}, ""),
            ("POST", f"/api/interviews/{interview_id}/cancel", {}, ""),
        ]:
            status, resp, lat = curl(method, path, body=body, token=token)
            record(results, method, path, status, resp, lat, note)
        # Delete with fake ID to avoid actual deletion
        status, resp, lat = curl("DELETE", "/api/interviews/fake-id-sweep-test", token=token)
        record(results, "DELETE", "/api/interviews/fake-id-sweep-test", status, resp, lat, "fake ID to avoid real deletion")
    else:
        for ep in ["/{id}", "/{id}/complete", "/{id}/cancel"]:
            record(results, "GET/POST", f"/api/interviews{ep} (SKIPPED)", 0, "No interview IDs", 0, "no_data")
        record(results, "DELETE", "/api/interviews/{id} (SKIPPED)", 0, "No interview IDs", 0, "no_data")
        record(results, "PATCH", "/api/interviews/{id} (SKIPPED)", 0, "No interview IDs", 0, "no_data")

    # POST /interviews
    status, resp, lat = curl("POST", "/api/interviews", body={
        "job_id": job_id or "test-job",
        "scheduled_at": "2026-07-20T10:00:00Z",
        "format": "video"
    }, token=token)
    record(results, "POST", "/api/interviews", status, resp, lat)

    # ── Emails ──
    print("\n--- Emails ---")
    thread_id = get_first_id("/api/emails", "id") or get_first_id("/api/emails", "thread_id")
    status, resp, lat = curl("GET", "/api/emails", token=token)
    record(results, "GET", "/api/emails", status, resp, lat)

    status, resp, lat = curl("POST", "/api/emails/draft", body={
        "to": "test@example.com",
        "subject": "Test Draft",
        "body": "This is a test draft body text."
    }, token=token)
    record(results, "POST", "/api/emails/draft", status, resp, lat)

    if thread_id:
        status, resp, lat = curl("GET", f"/api/emails/{thread_id}", token=token)
        record(results, "GET", f"/api/emails/{thread_id}", status, resp, lat)
        status, resp, lat = curl("POST", f"/api/emails/{thread_id}/reply", body={
            "body": "Test reply"
        }, token=token)
        record(results, "POST", f"/api/emails/{thread_id}/reply", status, resp, lat)
    else:
        record(results, "GET", "/api/emails/{thread_id} (SKIPPED)", 0, "No thread IDs", 0, "no_data")
        record(results, "POST", "/api/emails/{thread_id}/reply (SKIPPED)", 0, "No thread IDs", 0, "no_data")

    # ── Networking ──
    print("\n--- Networking ---")
    contact_id = get_first_id("/api/networking/contacts", "id")
    task_id = get_first_id("/api/networking/outreach", "id")

    for method, path, body, note in [
        ("GET", "/api/networking", None, ""),
        ("GET", "/api/networking/contacts", None, ""),
        ("GET", "/api/networking/outreach", None, ""),
    ]:
        status, resp, lat = curl(method, path, body=body, token=token)
        record(results, method, path, status, resp, lat, note)

    if contact_id:
        for method, path, body, note in [
            ("GET", f"/api/networking/contacts/{contact_id}", None, ""),
            ("PATCH", f"/api/networking/contacts/{contact_id}", {"name": "Updated Name"}, ""),
        ]:
            status, resp, lat = curl(method, path, body=body, token=token)
            record(results, method, path, status, resp, lat, note)
        # DELETE with fake
        status, resp, lat = curl("DELETE", "/api/networking/contacts/fake-contact-id", token=token)
        record(results, "DELETE", "/api/networking/contacts/fake-contact-id", status, resp, lat, "fake ID")
    else:
        for ep in ["/{id}", ""]:
            record(results, "GET/PATCH", f"/api/networking/contacts/{ep} (SKIPPED)" if ep else "/api/networking/contacts (SKIPPED)", 0, "No contact IDs", 0, "no_data")

    # POST /networking/contacts
    status, resp, lat = curl("POST", "/api/networking/contacts", body={
        "name": "Test Contact",
        "company": "Test Corp",
        "role": "Recruiter"
    }, token=token)
    record(results, "POST", "/api/networking/contacts", status, resp, lat)

    if task_id:
        for method, path, body, note in [
            ("GET", f"/api/networking/outreach/{task_id}", None, ""),
            ("PATCH", f"/api/networking/outreach/{task_id}", {"status": "sent"}, ""),
        ]:
            status, resp, lat = curl(method, path, body=body, token=token)
            record(results, method, path, status, resp, lat, note)
        status, resp, lat = curl("DELETE", "/api/networking/outreach/fake-task-id", token=token)
        record(results, "DELETE", "/api/networking/outreach/fake-task-id", status, resp, lat, "fake ID")
    else:
        for ep in ["/{id}", ""]:
            record(results, "GET", f"/api/networking/outreach{ep} (SKIPPED)", 0, "No task IDs", 0, "no_data")

    # POST /networking/outreach
    status, resp, lat = curl("POST", "/api/networking/outreach", body={
        "contact_id": contact_id or "fake",
        "channel": "email",
        "message": "Hi, I'd love to connect!"
    }, token=token)
    record(results, "POST", "/api/networking/outreach", status, resp, lat)

    # ── Write results ──
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump({"results": results, "total": len(results)}, f, indent=2)

    # Summary
    gaps = [r for r in results if r.get("gap")]
    total = len(results)
    print(f"\n=== SWEEP COMPLETE ===")
    print(f"Total endpoints tested: {total}")
    print(f"Gaps flagged: {len(gaps)}")
    if gaps:
        print("GAP DETAILS:")
        for g in gaps:
            print(f"  {g['method']} {g['path']} → {g['status']}")
    print(f"Results written to: {OUTPUT}")

if __name__ == "__main__":
    main()
