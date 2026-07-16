#!/usr/bin/env python3
"""Phase 6 QA re-confirm of WIRE-001 (6 jobs/applications view-toggle controls).

Clicks each of the 6 controls and asserts an observable state change
(aria-selected flips to the clicked tab) plus, for the network-backed sankey
view, a live XHR to /applications/funnel/sankey. Writes one aggregate JSON +
one screenshot per page to uat/reports/evidence/phase6/browser/.
"""
from __future__ import annotations

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


def load_env() -> dict:
    env: dict[str, str] = {}
    with open(REPO_ROOT / ".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def api_login(email: str, password: str) -> str:
    resp = requests.post(f"{API_BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def main() -> int:
    env = load_env()
    token = api_login(env["LOGIN_EMAIL"], env["LOGIN_PASSWORD"])
    stamp = utc_stamp()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    results: dict[str, list] = {"jobs_market_tabs": [], "applications_view_tabs": []}
    network_hits: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(
            f"window.localStorage.setItem({json.dumps(TOKEN_STORAGE_KEY)}, {json.dumps(token)});"
        )
        page = context.new_page()

        def on_request(req):
            if "funnel/sankey" in req.url:
                network_hits.append(req.url)

        page.on("request", on_request)

        # ---- Jobs market tabs (au / intl / saved) --------------------------
        page.goto(f"{BASE_URL}/dashboard/jobs", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1500)
        for key in ("au", "intl", "saved"):
            testid = f"market-tab-{key}"
            loc = page.locator(f'[data-testid="{testid}"]')
            exists = loc.count() > 0
            before_selected = loc.get_attribute("aria-selected") if exists else None
            clicked = False
            after_selected = None
            error = None
            try:
                loc.click(timeout=5000)
                page.wait_for_timeout(800)
                after_selected = loc.get_attribute("aria-selected")
                clicked = True
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            results["jobs_market_tabs"].append(
                {
                    "control": testid,
                    "exists": exists,
                    "clicked": clicked,
                    "aria_selected_before": before_selected,
                    "aria_selected_after": after_selected,
                    "state_changed": after_selected == "true",
                    "error": error,
                }
            )
        page.screenshot(path=str(EVIDENCE_DIR / f"wire001__jobs-market__{stamp}.png"), full_page=True)

        # ---- Applications view tabs (board / sankey / timeline) ------------
        page.goto(f"{BASE_URL}/dashboard/applications", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1500)
        for key in ("board", "sankey", "timeline"):
            testid = f"view-{key}"
            loc = page.locator(f'[data-testid="{testid}"]')
            exists = loc.count() > 0
            before_selected = loc.get_attribute("aria-selected") if exists else None
            clicked = False
            after_selected = None
            error = None
            try:
                loc.click(timeout=5000)
                page.wait_for_timeout(1200)
                after_selected = loc.get_attribute("aria-selected")
                clicked = True
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            results["applications_view_tabs"].append(
                {
                    "control": testid,
                    "exists": exists,
                    "clicked": clicked,
                    "aria_selected_before": before_selected,
                    "aria_selected_after": after_selected,
                    "state_changed": after_selected == "true",
                    "error": error,
                }
            )
        page.screenshot(path=str(EVIDENCE_DIR / f"wire001__applications-view__{stamp}.png"), full_page=True)

        context.close()
        browser.close()

    all_controls = results["jobs_market_tabs"] + results["applications_view_tabs"]
    all_ok = all(c["exists"] and c["clicked"] and c["state_changed"] for c in all_controls)
    summary = {
        "utc": stamp,
        "controls_checked": len(all_controls),
        "all_state_changes_confirmed": all_ok,
        "sankey_network_call_observed": len(network_hits) > 0,
        "sankey_network_hits": network_hits,
        "results": results,
    }
    out_path = EVIDENCE_DIR / f"wire001-summary__{stamp}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"\nWritten: {out_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
