#!/usr/bin/env python3
"""Phase 6 QA console-cleanliness sweep (GATE-03) + WIRE-001 re-confirm.

Pattern reused from uat/phase4_sweep.py (real API login -> inject bearer token
into localStorage the same way the app does -> navigate -> capture console
errors / pageerrors / requestfailed / response>=400). This variant sweeps a
LIST of routes in one browser context (one screenshot+console log per route)
and additionally emits a single aggregate JSON summary suitable for a gate
verdict, into uat/reports/evidence/phase6/browser/.

Usage:
    python3 uat/phase6_console_sweep.py --as nonadmin
    python3 uat/phase6_console_sweep.py --as admin --admin-email X --admin-password Y
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE_URL = "https://5cb5f0620.abacusai.cloud"
API_BASE = f"{BASE_URL}/api"
TOKEN_STORAGE_KEY = "aether_token"

REPO_ROOT = Path("/home/ubuntu/github_repos/aether-job-career-agent")
EVIDENCE_DIR = REPO_ROOT / "uat/reports/evidence/phase6/browser"

ROUTES = [
    "/dashboard",
    "/dashboard/jobs",
    "/dashboard/applications",
    "/dashboard/resume",
    "/dashboard/cover-letters",
    "/dashboard/email",
    "/dashboard/interviews",
    "/dashboard/networking",
    "/dashboard/offers",
    "/dashboard/analytics",
    "/dashboard/agents",
    "/dashboard/stories",
    "/dashboard/approvals",
    "/dashboard/settings",
    "/pricing",
    "/admin",
]


def load_env() -> dict:
    env_path = REPO_ROOT / ".env"
    env: dict[str, str] = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def api_login(email: str, password: str) -> str:
    resp = requests.post(
        f"{API_BASE}/auth/login", json={"email": email, "password": password}, timeout=30
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API login failed: HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"Login response missing access_token: {body}")
    return token


def slug(route: str) -> str:
    return route.strip("/").replace("/", "-") or "root"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as", dest="role", choices=["nonadmin", "admin"], required=True)
    ap.add_argument("--admin-email", default=None)
    ap.add_argument("--admin-password", default=None)
    args = ap.parse_args()

    env = load_env()
    if args.role == "nonadmin":
        email, password = env["LOGIN_EMAIL"], env["LOGIN_PASSWORD"]
    else:
        if not args.admin_email or not args.admin_password:
            print("admin role requires --admin-email/--admin-password", file=sys.stderr)
            return 2
        email, password = args.admin_email, args.admin_password

    stamp = utc_stamp()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        token = api_login(email, password)
    except Exception as exc:  # noqa: BLE001
        print(f"LOGIN FAILED: {exc}", file=sys.stderr)
        return 2

    per_route: list[dict] = []
    all_console_errors: list[dict] = []
    all_failed_requests: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(
            f"window.localStorage.setItem({json.dumps(TOKEN_STORAGE_KEY)}, {json.dumps(token)});"
        )

        for route in ROUTES:
            events: list[dict] = []

            def log_event(kind: str, payload: dict) -> None:
                events.append({"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **payload})

            page = context.new_page()
            page.on(
                "console",
                lambda msg: log_event(
                    "console", {"level": msg.type, "text": msg.text, "location": str(msg.location)}
                ),
            )
            page.on("pageerror", lambda exc: log_event("pageerror", {"message": str(exc)}))

            def on_reqfailed(req):
                log_event(
                    "requestfailed",
                    {
                        "url": req.url,
                        "method": req.method,
                        "failure": (req.failure or {}).get("errorText") if req.failure else None,
                    },
                )

            page.on("requestfailed", on_reqfailed)

            def on_response(resp):
                if resp.status >= 400:
                    log_event(
                        "response>=400", {"url": resp.url, "status": resp.status, "status_text": resp.status_text}
                    )

            page.on("response", on_response)

            nav_error = None
            try:
                page.goto(f"{BASE_URL}{route}", wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001
                nav_error = f"{type(exc).__name__}: {exc}"

            final_url = page.url
            s = slug(route)
            screenshot_path = EVIDENCE_DIR / f"gate03__{args.role}__{s}__{stamp}.png"
            console_path = EVIDENCE_DIR / f"gate03__{args.role}__{s}__{stamp}.log"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception as exc:  # noqa: BLE001
                log_event("error", {"message": f"screenshot failed: {exc}"})

            title = None
            try:
                title = page.title()
            except Exception:  # noqa: BLE001
                pass

            page.close()

            with open(console_path, "w") as f:
                for ev in events:
                    f.write(json.dumps(ev) + "\n")

            console_errors = [e for e in events if e["kind"] == "console" and e.get("level") == "error"]
            pageerrors = [e for e in events if e["kind"] == "pageerror"]
            req_failed = [e for e in events if e["kind"] == "requestfailed"]
            bad_responses = [e for e in events if e["kind"] == "response>=400"]

            # Filter out well-known non-app-fault noise the same way the recipe
            # frames it: external adapter probes / expected 4xx auth checks are
            # NOT the target of GATE-03 (which is about the APP's own console),
            # but we record everything raw and only classify, never discard.
            route_summary = {
                "route": route,
                "final_url": final_url,
                "title": title,
                "nav_error": nav_error,
                "bounced_to_login": "/login" in final_url and "/login" not in route,
                "console_error_count": len(console_errors),
                "pageerror_count": len(pageerrors),
                "requestfailed_count": len(req_failed),
                "response_4xx5xx_count": len(bad_responses),
                "console_errors": console_errors,
                "pageerrors": pageerrors,
                "requestfailed": req_failed,
                "bad_responses": bad_responses,
                "screenshot": str(screenshot_path),
                "console_log": str(console_path),
            }
            per_route.append(route_summary)
            all_console_errors.extend(console_errors)
            all_failed_requests.extend(req_failed + bad_responses)
            print(
                f"route={route} nav_error={nav_error} bounced={route_summary['bounced_to_login']} "
                f"console_err={len(console_errors)} pageerr={len(pageerrors)} "
                f"reqfailed={len(req_failed)} bad_resp={len(bad_responses)}"
            )

        context.close()
        browser.close()

    summary = {
        "role": args.role,
        "login_email": email,
        "utc": stamp,
        "base_url": BASE_URL,
        "routes_swept": ROUTES,
        "route_count": len(ROUTES),
        "total_console_errors": len(all_console_errors),
        "total_failed_requests": len(all_failed_requests),
        "per_route": per_route,
    }
    summary_path = EVIDENCE_DIR / f"gate03-summary__{args.role}__{stamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSUMMARY written: {summary_path}")
    print(f"total_console_errors={len(all_console_errors)} total_failed_requests={len(all_failed_requests)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
