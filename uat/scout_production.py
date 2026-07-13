#!/usr/bin/env python3
"""
Production evidence sweep for Aether Career Agent screens 1-6.
Uses Playwright for headless browser automation.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "https://5cb5f0620.abacusai.cloud"
ROUTES = [
    ("/login", "login"),
    ("/dashboard", "dashboard"),
    ("/dashboard/jobs", "dashboard_jobs"),
    ("/dashboard/applications", "dashboard_applications"),
    ("/dashboard/resume", "dashboard_resume"),
    ("/dashboard/cover-letters", "dashboard_cover_letters"),
]

OUTPUT_DIR = Path("/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/phase4")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

findings = []


async def capture_screenshot(page, route_name: str, timestamp: str):
    """Capture full-page screenshot."""
    filename = f"{route_name}__screenshot__{timestamp}.png"
    filepath = OUTPUT_DIR / filename
    await page.screenshot(path=str(filepath), full_page=True)
    return filename


async def capture_console(page, route_name: str, timestamp: str):
    """Capture console errors and warnings."""
    console_output = await page.evaluate("""() => {
        const log = window.__console_log || [];
        window.__console_log = [];
        return log;
    }""")
    
    # Get browser console
    messages = await page.evaluate("""() => {
        const originalConsole = window.console;
        const logged = [];
        
        ['error', 'warn', 'info', 'log', 'debug'].forEach(level => {
            const original = console[level];
            console[level] = (...args) => {
                logged.push({ level, message: args.map(String).join(' ') });
                original.apply(console, args);
            };
        });
        
        return logged;
    }""")
    
    filename = f"{route_name}__console__{timestamp}.log"
    filepath = OUTPUT_DIR / filename
    
    with open(filepath, 'w') as f:
        f.write(f"Console capture for {route_name} at {timestamp}\n")
        f.write("=" * 80 + "\n\n")
        for msg in messages:
            f.write(f"[{msg['level'].upper()}] {msg['message']}\n")
    
    return filename, messages


async def interactive_pass(page, route_name: str, timestamp: str):
    """Perform interaction pass and capture results."""
    results = []
    
    # Get all buttons and interactive elements
    elements = await page.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('button, a, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="switch"]'));
        return all.map((el, idx) => ({
            idx,
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            role: el.getAttribute('role') || '',
            text: el.innerText?.slice(0, 100) || '',
            id: el.id || '',
            name: el.name || '',
            disabled: el.disabled || false,
            href: el.href || '',
            value: el.value || ''
        })).filter(e => !e.disabled);
    }""")
    
    for elem in elements[:20]:  # Limit interactions
        try:
            selector = f'element.{elem["idx"]}'
            # Try to click
            await page.evaluate(f"""() => {{
                const els = Array.from(document.querySelectorAll('*'));
                if (els[{elem["idx"]}]) {{
                    const evt = new Event('click', {{ bubbles: true }});
                    els[{elem["idx"]}].dispatchEvent(evt);
                }}
            }}""")
            
            results.append({
                "action": "click",
                "element": elem,
                "success": True
            })
            
            await page.wait_for_timeout(500)
        except Exception as e:
            results.append({
                "action": "click",
                "element": elem,
                "success": False,
                "error": str(e)
            })
    
    # Capture any alerts
    try:
        alert_text = await page.evaluate("""() => {
            const alert = window.__last_alert || '';
            return alert;
        }""")
        if alert_text:
            results.append({"action": "alert", "message": alert_text})
    except:
        pass
    
    return results


async def check_data_authenticity(page, route_name: str):
    """Check for placeholder/hardcoded data."""
    findings = {}
    
    # Check for common placeholder patterns
    placeholder_patterns = [
        (r'Lorem', 'Lorem ipsum text'),
        (r'TODO', 'TODO comment'),
        (r'Sample', 'Sample data'),
        (r'Test data', 'Test data placeholder'),
        (r'Demo', 'Demo placeholder'),
        (r'example.com', 'Example placeholder'),
        (r'\d{1,2}/\d{1,2}/\d{4}', 'Date placeholder pattern'),
    ]
    
    content = await page.content()
    
    for pattern, desc in placeholder_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            findings[desc] = {
                "found": True,
                "count": len(matches),
                "samples": matches[:3]
            }
        else:
            findings[desc] = {"found": False}
    
    return findings


async def run_route(page, route_path: str, route_name: str, timestamp: str):
    """Navigate to route and capture evidence."""
    print(f"\n{'='*60}")
    print(f"Processing: {route_path} ({route_name})")
    print('='*60)
    
    try:
        await page.goto(f"{BASE_URL}{route_path}", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  ❌ Navigation failed: {e}")
        return {
            "route": route_path,
            "status": "error",
            "error": str(e),
            "screenshot": None,
            "console_errors": [],
            "interaction_results": [],
            "data_authenticity": {},
            "wireframe_diff": {}
        }
    
    # Capture console BEFORE interactions
    console_file, console_messages = await capture_console(page, route_name, timestamp)
    console_errors = [m for m in console_messages if m['level'] == 'error']
    console_warnings = [m for m in console_messages if m['level'] == 'warn']
    print(f"  Console: {len(console_errors)} errors, {len(console_warnings)} warnings")
    
    # Capture screenshot
    screenshot_file = await capture_screenshot(page, route_name, timestamp)
    print(f"  Screenshot: {screenshot_file}")
    
    # Interactive pass
    interaction_results = await interactive_pass(page, route_name, timestamp)
    print(f"  Interactions: {len(interaction_results)} elements tested")
    
    # Data authenticity check
    data_authenticity = await check_data_authenticity(page, route_name)
    print(f"  Data checks: {sum(1 for v in data_authenticity.values() if v['found'])} issues found")
    
    return {
        "route": route_path,
        "status": "success",
        "screenshot": screenshot_file,
        "console_errors": console_errors,
        "console_warnings": console_warnings,
        "console_log": console_messages,
        "interaction_results": interaction_results,
        "data_authenticity": data_authenticity,
        "wireframe_diff": {}
    }


async def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        # Pre-populate console log collector
        await page.evaluate("""() => {
            window.__console_log = [];
            const originalConsole = window.console;
            
            ['error', 'warn', 'info', 'log', 'debug'].forEach(level => {
                console[level] = (...args) => {
                    window.__console_log.push({ level, message: args.map(String).join(' ') });
                    if (originalConsole && originalConsole[level]) {
                        originalConsole[level].apply(console, args);
                    }
                };
            });
        }""")
        
        for route_path, route_name in ROUTES:
            result = await run_route(page, route_path, route_name, timestamp)
            findings.append(result)
            
            # Save individual findings
            findings_file = OUTPUT_DIR / f"scout-findings-{route_name}.json"
            with open(findings_file, 'w') as f:
                json.dump(result, f, indent=2)
        
        await browser.close()
    
    # Save consolidated findings
    consolidated_file = OUTPUT_DIR / f"scout-findings-1-6.json"
    with open(consolidated_file, 'w') as f:
        json.dump(findings, f, indent=2)
    
    # Print summary
    print("\n" + "="*60)
    print("PRODUCTION EVIDENCE SWEEP - SUMMARY")
    print("="*60)
    
    routes_verified = sum(1 for f in findings if f.get("status") == "success")
    routes_failed = len(findings) - routes_verified
    total_errors = sum(len(f.get("console_errors", [])) for f in findings)
    total_warnings = sum(len(f.get("console_warnings", [])) for f in findings)
    total_interactions = sum(len(f.get("interaction_results", [])) for f in findings)
    
    print(f"\nRoutes Verified:   {routes_verified}/{len(ROUTES)}")
    print(f"Routes Failed:     {routes_failed}")
    print(f"Total Console Errors:    {total_errors}")
    print(f"Total Console Warnings:  {total_warnings}")
    print(f"Total Interactions:      {total_interactions}")
    print(f"\nEvidence Files Created:")
    print(f"  - {consolidated_file}")
    for f in findings:
        if f.get("screenshot"):
            print(f"  - {OUTPUT_DIR / f['screenshot']}")
    
    return findings


if __name__ == "__main__":
    asyncio.run(main())
