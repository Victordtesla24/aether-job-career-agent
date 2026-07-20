#!/usr/bin/env python3
"""MANUAL-VERIFICATION Phase 0 baseline sweep — captures evidence for all 29 screens.

Deterministic sweep of the production Aether Career Agent (https://5cb5f0620.abacusai.cloud)
to establish a baseline of what pages load, console errors/warnings, network failures, and
HTTP status codes BEFORE any fixes are applied.

For each screen in SCREEN-MATRIX.json:
  - Authenticated dashboard/feature screens: logs in first (admin/admin123), then navigates
  - Unauthenticated screens (login, signup, pricing, etc.): visits directly
  - Admin screens: visits both unauthenticated (expect 401/redirect) AND authenticated
  - Mobile screens: uses viewport 390x844 (iPhone-ish)
  - Root (/): captures redirect chains both unauthenticated and authenticated
  - Catch-all (/dashboard/[...slug]): visits a bogus path to see 404 behavior

Outputs per screen:
  - uat/reports/evidence/manual-verification/screens/<screen_id>/baseline/screenshot.png
  - uat/reports/evidence/manual-verification/screens/<screen_id>/baseline/console.json
  - uat/reports/evidence/manual-verification/screens/<screen_id>/baseline/network-failures.json
  - uat/reports/evidence/manual-verification/screens/<screen_id>/baseline/status.txt
  - uat/reports/evidence/manual-verification/screens/<screen_id>/baseline/SUMMARY.json

And top-level manifest:
  - uat/reports/evidence/manual-verification/screens/BASELINE-SWEEP.json

Exit code 0 if all screens captured successfully; non-zero if any critical screens fail.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import sync_playwright

BASE_URL = "https://5cb5f0620.abacusai.cloud"
API_BASE = f"{BASE_URL}/api"
TOKEN_STORAGE_KEY = "aether_token"
REPO_ROOT = Path("/home/ubuntu/github_repos/aether-job-career-agent")
SCREEN_MATRIX_PATH = REPO_ROOT / "uat/reports/evidence/manual-verification/screens/SCREEN-MATRIX.json"
BASELINE_ROOT = REPO_ROOT / "uat/reports/evidence/manual-verification/screens"


def load_env() -> dict:
    """Parse repo-root .env."""
    env_path = REPO_ROOT / ".env"
    env: dict[str, str] = {}
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        print(f"WARNING: .env not found at {env_path}, using fallback credentials", file=sys.stderr)
        # Use canonical hardcoded creds if .env missing (since canonical-login.md says admin/admin123)
        env = {"LOGIN_EMAIL": "admin", "LOGIN_PASSWORD": "admin123"}
    return env


def load_screen_matrix() -> list[dict]:
    """Load SCREEN-MATRIX.json."""
    with open(SCREEN_MATRIX_PATH) as f:
        return json.load(f)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def api_login(email: str, password: str) -> str | None:
    """Log in against the real API. Returns token or None on failure."""
    try:
        resp = requests.post(f"{API_BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
        if resp.status_code != 200:
            return None
        body = resp.json()
        return body.get("access_token")
    except Exception:
        return None


def capture_screen(
    screen_id: str,
    route: str,
    token: str | None = None,
    viewport: dict | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Capture a single screen. Returns status dict."""
    if viewport is None:
        viewport = {"width": 1440, "height": 900}

    stamp = utc_stamp()
    screen_dir = BASELINE_ROOT / screen_id / "baseline"
    screen_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path = screen_dir / "screenshot.png"
    console_path = screen_dir / "console.json"
    network_failures_path = screen_dir / "network-failures.json"
    status_path = screen_dir / "status.txt"
    summary_path = screen_dir / "SUMMARY.json"

    events: list[dict] = []
    network_failures: list[dict] = []
    http_status = None
    page_error = None

    def log_event(kind: str, payload: dict) -> None:
        events.append({"ts": stamp, "kind": kind, **payload})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport=viewport)

            # Inject token if provided
            if token:
                context.add_init_script(
                    f"window.localStorage.setItem({json.dumps(TOKEN_STORAGE_KEY)}, {json.dumps(token)});"
                )

            page = context.new_page()

            # Capture page response status
            def on_response(resp):
                nonlocal http_status
                if http_status is None and resp.url == f"{BASE_URL}{route}":
                    http_status = resp.status
                if resp.status >= 400:
                    network_failures.append(
                        {"method": resp.request.method, "url": resp.url, "status": resp.status}
                    )

            # Capture console
            page.on("console", lambda msg: log_event("console", {"level": msg.type, "text": msg.text}))
            page.on("pageerror", lambda exc: log_event("pageerror", {"message": str(exc)}))
            page.on("requestfailed", lambda req: log_event("requestfailed", {"url": req.url, "method": req.method}))
            page.on("response", on_response)

            # Navigate
            try:
                page.goto(f"{BASE_URL}{route}", wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(1000)
            except Exception as exc:
                page_error = f"{type(exc).__name__}: {str(exc)[:100]}"
                log_event("navigation_error", {"error": page_error})

            # Screenshot
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception as exc:
                log_event("error", {"message": f"screenshot failed: {exc}"})

            # Get title
            title = None
            try:
                title = page.title()
            except Exception:
                pass

            final_url = page.url
            context.close()
            browser.close()

    except Exception as exc:
        log_event("error", {"message": f"playwright crashed: {exc}"})
        final_url = ""

    # Write artifacts
    console_errors = sum(1 for e in events if e.get("kind") == "console" and e.get("level") == "error")
    console_warnings = sum(1 for e in events if e.get("kind") == "console" and e.get("level") == "warning")

    with open(console_path, "w") as f:
        json.dump(events, f, indent=2)

    with open(network_failures_path, "w") as f:
        json.dump(network_failures, f, indent=2)

    if http_status is not None:
        with open(status_path, "w") as f:
            f.write(str(http_status))

    summary = {
        "screen_id": screen_id,
        "route": route,
        "url": f"{BASE_URL}{route}",
        "ts_utc": stamp,
        "http_status": http_status,
        "console_error_count": console_errors,
        "console_warning_count": console_warnings,
        "failed_request_count": len(network_failures),
        "notes": description,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    return {
        "screen_id": screen_id,
        "route": route,
        "http_status": http_status,
        "console_errors": console_errors,
        "console_warnings": console_warnings,
        "failed_requests": len(network_failures),
        "screenshot_path": str(screenshot_path),
        "error": page_error,
    }


def main() -> int:
    env = load_env()
    screens = load_screen_matrix()

    token = api_login(env.get("LOGIN_EMAIL", "admin"), env.get("LOGIN_PASSWORD", "admin123"))
    if not token:
        print("ERROR: Could not obtain auth token", file=sys.stderr)
        return 2

    ts_start = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []
    rows_captured = 0
    rows_failed = 0
    total_console_errors = 0
    total_failed_requests = 0

    for screen in screens:
        screen_id = screen["screen_id"]
        routes = screen.get("routes", [])
        primary_route = routes[0] if routes else "/"

        print(f"Capturing {screen_id}...", end=" ", flush=True)

        # Determine capture strategy
        if screen_id == "root":
            # Root: capture unauthenticated redirect, then authenticated redirect
            print(f"(unauthenticated & authenticated redirects)", flush=True)
            result_unauth = capture_screen(screen_id, "/", token=None, description="unauthenticated redirect")
            result_auth = capture_screen(screen_id, "/", token=token, description="authenticated redirect")
            result = result_auth
            if result["http_status"]:
                rows_captured += 1
            else:
                rows_failed += 1

        elif screen_id.startswith("mobile-"):
            # Mobile: use iPhone viewport
            vp = {"width": 390, "height": 844}
            print(f"(mobile viewport 390x844)", flush=True)
            result = capture_screen(screen_id, primary_route, token=token, viewport=vp)
            if result["http_status"]:
                rows_captured += 1
            else:
                rows_failed += 1

        elif screen_id.startswith("admin-"):
            # Admin: capture unauthenticated (expect denial), then authenticated (expect denial too since admin/admin123 is non-admin)
            print(f"(unauthenticated & authenticated attempts)", flush=True)
            result_unauth = capture_screen(
                f"{screen_id}_unauth", primary_route, token=None, description="unauthenticated (expect 401/redirect)"
            )
            result_auth = capture_screen(
                f"{screen_id}_auth", primary_route, token=token, description="authenticated non-admin (expect denied)"
            )
            result = result_auth
            if result["http_status"] in (401, 403, 302):
                rows_captured += 1
            else:
                rows_failed += 1

        elif screen_id == "dashboard":
            # Dashboard: capture normal, then catch-all path
            print(f"(normal + catch-all /dashboard/nonexistent-xyz)", flush=True)
            result = capture_screen(screen_id, primary_route, token=token)
            result_catchall = capture_screen(
                f"{screen_id}_catchall", "/dashboard/nonexistent-xyz", token=token, description="catch-all 404 handler"
            )
            if result["http_status"]:
                rows_captured += 1
            else:
                rows_failed += 1

        else:
            # Standard authenticated screen
            is_unauth = screen_id in ("login", "signup", "pricing", "privacy-policy", "terms")
            if is_unauth:
                print(f"(unauthenticated)", flush=True)
                result = capture_screen(screen_id, primary_route, token=None)
            else:
                print(f"(authenticated)", flush=True)
                result = capture_screen(screen_id, primary_route, token=token)

            if result["http_status"]:
                rows_captured += 1
            else:
                rows_failed += 1

        total_console_errors += result["console_errors"]
        total_failed_requests += result["failed_requests"]
        results.append(result)

    ts_end = datetime.now(timezone.utc).isoformat()

    # Write manifest
    worst_screens = sorted(results, key=lambda r: r["console_errors"] + r["failed_requests"], reverse=True)[:5]

    manifest = {
        "ts_start_utc": ts_start,
        "ts_end_utc": ts_end,
        "git_sha": "HEAD",  # Could parse from git if needed
        "rows_captured": rows_captured,
        "rows_failed": rows_failed,
        "total_console_errors": total_console_errors,
        "total_failed_requests": total_failed_requests,
        "worst_screens": worst_screens,
        "rows": results,
    }

    manifest_path = BASELINE_ROOT / "BASELINE-SWEEP.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n✓ Baseline sweep complete")
    print(f"  Captured: {rows_captured}/{len(screens)}")
    print(f"  Failed: {rows_failed}/{len(screens)}")
    print(f"  Total console errors: {total_console_errors}")
    print(f"  Total failed requests: {total_failed_requests}")
    print(f"  Manifest: {manifest_path}")

    return 0 if rows_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
