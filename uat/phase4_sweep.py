#!/usr/bin/env python3
"""Phase 4 per-route production evidence sweep for Aether Career Agent.

Reusable CLI for scout agents auditing the deployed production app
(https://5cb5f0620.abacusai.cloud). Logs in via the real API, injects the
resulting bearer token into the browser the same way the app itself does
(localStorage["aether_token"] — see apps/web/src/app/login/page.tsx and
apps/web/src/components/auth-guard.tsx), navigates to the requested route,
and captures four deterministic evidence artifacts:

    <prefix>__screenshot__<utc>.png   full-page screenshot
    <prefix>__console__<utc>.log      ALL console msgs + pageerrors +
                                      requestfailed + responses >=400
                                      (unfiltered JSONL, one event/line)
    <prefix>__controls__<utc>.json    accessibility-style dump of
                                      interactive elements
    <prefix>__meta__<utc>.json        url, viewport, utc, title

Usage:
    python3 uat/phase4_sweep.py --route /dashboard --out-prefix dashboard \
        [--viewport 1440x900]

Exit code 0 on success (login succeeded, navigation completed, all four
artifacts written); non-zero otherwise.
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
CREDS = {"email": "sarkar.vikram@gmail.com", "password": "AetherDemo1"}
TOKEN_STORAGE_KEY = "aether_token"  # must match apps/web/src/app/login/page.tsx

EVIDENCE_DIR = Path(
    "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/phase4"
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_viewport(spec: str) -> dict:
    try:
        w, h = spec.lower().split("x")
        return {"width": int(w), "height": int(h)}
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"invalid --viewport '{spec}', expected WxH e.g. 1440x900") from exc


def api_login() -> str:
    """Log in against the real API and return the bearer access_token.

    Mirrors POST /api/auth/login exactly as apps/web/src/app/login/page.tsx
    does from the browser.
    """
    resp = requests.post(f"{API_BASE}/auth/login", json=CREDS, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(
            f"API login failed: HTTP {resp.status_code}: {resp.text[:200]}"
        )
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"API login response missing access_token: {body}")
    return token


CONTROLS_JS = """() => {
    const sel = 'button, a, input, select, textarea, [role="button"], ' +
                '[role="link"], [role="checkbox"], [role="switch"], [role="tab"], ' +
                '[role="menuitem"]';
    const els = Array.from(document.querySelectorAll(sel));
    return els.map((el, idx) => {
        const rect = el.getBoundingClientRect();
        return {
            idx,
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            role: el.getAttribute('role') || '',
            name: el.getAttribute('name') || '',
            id: el.id || '',
            text: (el.innerText || el.value || '').trim().slice(0, 150),
            ariaLabel: el.getAttribute('aria-label') || '',
            testId: el.getAttribute('data-testid') || '',
            href: el.tagName.toLowerCase() === 'a' ? (el.getAttribute('href') || '') : '',
            disabled: !!el.disabled,
            visible: rect.width > 0 && rect.height > 0,
        };
    });
}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", required=True, help="path e.g. /dashboard")
    parser.add_argument("--out-prefix", required=True, help="artifact filename prefix")
    parser.add_argument("--viewport", default="1440x900", help="WxH, default 1440x900")
    args = parser.parse_args()

    route = args.route if args.route.startswith("/") else f"/{args.route}"
    prefix = args.out_prefix
    viewport = parse_viewport(args.viewport)
    stamp = utc_stamp()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    screenshot_path = EVIDENCE_DIR / f"{prefix}__screenshot__{stamp}.png"
    console_path = EVIDENCE_DIR / f"{prefix}__console__{stamp}.log"
    controls_path = EVIDENCE_DIR / f"{prefix}__controls__{stamp}.json"
    meta_path = EVIDENCE_DIR / f"{prefix}__meta__{stamp}.json"

    # ---- Auth: real API login, then inject the token the way the app does ---
    try:
        token = api_login()
    except Exception as exc:  # noqa: BLE001
        print(f"LOGIN FAILED: {exc}", file=sys.stderr)
        return 2

    events: list[dict] = []

    def log_event(kind: str, payload: dict) -> None:
        events.append({"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **payload})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=viewport)

        # Inject the bearer token into localStorage before any app script runs,
        # on every navigation in this context — same key/mechanism the real
        # /login page and AuthGuard use (apps/web/src/components/auth-guard.tsx).
        context.add_init_script(
            f"window.localStorage.setItem({json.dumps(TOKEN_STORAGE_KEY)}, {json.dumps(token)});"
        )

        page = context.new_page()

        page.on(
            "console",
            lambda msg: log_event(
                "console",
                {"level": msg.type, "text": msg.text, "location": str(msg.location)},
            ),
        )
        page.on(
            "pageerror",
            lambda exc: log_event("pageerror", {"message": str(exc)}),
        )
        page.on(
            "requestfailed",
            lambda req: log_event(
                "requestfailed",
                {
                    "url": req.url,
                    "method": req.method,
                    "failure": (req.failure or {}).get("errorText") if req.failure else None,
                },
            ),
        )

        def on_response(resp):
            if resp.status >= 400:
                log_event(
                    "response>=400",
                    {"url": resp.url, "status": resp.status, "status_text": resp.status_text},
                )

        page.on("response", on_response)

        nav_error: str | None = None
        try:
            page.goto(f"{BASE_URL}{route}", wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2000)
        except Exception as exc:  # noqa: BLE001
            nav_error = f"{type(exc).__name__}: {exc}"

        # Verify auth actually took (not silently bounced to /login).
        current_url = page.url
        bounced_to_login = "/login" in current_url and "/login" not in route

        # ---- Screenshot ------------------------------------------------------
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as exc:  # noqa: BLE001
            log_event("error", {"message": f"screenshot failed: {exc}"})

        # ---- Controls dump -----------------------------------------------------
        try:
            controls = page.evaluate(CONTROLS_JS)
        except Exception as exc:  # noqa: BLE001
            controls = []
            log_event("error", {"message": f"controls dump failed: {exc}"})

        title = None
        try:
            title = page.title()
        except Exception:  # noqa: BLE001
            pass

        context.close()
        browser.close()

    # ---- Write console/network JSONL (unfiltered) ---------------------------
    with open(console_path, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    # ---- Write controls dump --------------------------------------------------
    with open(controls_path, "w") as f:
        json.dump({"route": route, "count": len(controls), "elements": controls}, f, indent=2)

    # ---- Write meta -----------------------------------------------------------
    meta = {
        "url": f"{BASE_URL}{route}",
        "final_url": current_url,
        "viewport": viewport,
        "utc": stamp,
        "title": title,
        "nav_error": nav_error,
        "bounced_to_login": bounced_to_login,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    ok = nav_error is None and not bounced_to_login
    for p_ in (screenshot_path, console_path, controls_path, meta_path):
        if not p_.exists():
            ok = False

    print(f"route={route} prefix={prefix} ok={ok}")
    print(f"  screenshot: {screenshot_path}")
    print(f"  console:    {console_path}")
    print(f"  controls:   {controls_path}")
    print(f"  meta:       {meta_path}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
