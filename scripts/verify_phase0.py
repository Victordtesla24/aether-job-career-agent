#!/usr/bin/env python3
"""Phase 0 wireframe verification harness (design-system + structural checks).

Read-only. Prints a report and exits non-zero if any HARD check fails.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ROOT / "design" / "screens"

# Core desktop screens that MUST carry the identical 12-item Schema A sidebar.
CORE_SCREENS = [
    "dashboard.html",
    "job-discovery.html",
    "resume-studio.html",
    "story-bank.html",
    "application-tracker.html",
    "interview-center.html",
    "networking.html",
    "email-center.html",
    "agents.html",
    "analytics.html",
    "offer-comparison.html",
    "settings.html",
    "cover-letter-studio.html",  # new P3 screen (sub-feature of Resume Studio)
]

SIDEBAR_LABELS = [
    "Dashboard", "Jobs", "Resume Studio", "Story Bank", "Applications",
    "Interview Center", "Networking", "Email Center", "Agents",
    "Analytics", "Offers", "Settings",
]

DESIGN_TOKENS = {
    "bg": "#0A0A0F",
    "coral": "#FF6B35",
}

hard_fail = []
soft_warn = []
report = []


def check(name, ok, detail="", hard=True):
    status = "PASS" if ok else ("FAIL" if hard else "WARN")
    report.append(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        (hard_fail if hard else soft_warn).append(f"{name}: {detail}")


def tag_balance(text, tag):
    opens = len(re.findall(rf"<{tag}[\s>]", text))
    closes = len(re.findall(rf"</{tag}>", text))
    return opens, closes


# ---- Per-screen checks ----
for fn in CORE_SCREENS:
    p = SCREENS / fn
    if not p.exists():
        check(f"{fn} exists", False, "file missing")
        continue
    text = p.read_text(encoding="utf-8")

    # div balance
    do, dc = tag_balance(text, "div")
    check(f"{fn} div balance", do == dc, f"open={do} close={dc}")

    # script balance
    so, sc = tag_balance(text, "script")
    check(f"{fn} script balance", so == sc, f"open={so} close={sc}")

    # 12 sidebar labels present
    missing = [lbl for lbl in SIDEBAR_LABELS if lbl not in text]
    check(f"{fn} 12-item sidebar", not missing, f"missing={missing}")

    # design tokens
    check(f"{fn} bg token {DESIGN_TOKENS['bg']}", DESIGN_TOKENS["bg"] in text, "", hard=False)
    check(f"{fn} coral token {DESIGN_TOKENS['coral']}", DESIGN_TOKENS["coral"] in text)

    # duplicate design-ids (real HTML attribute duplicates only — dedupe by counting
    # attribute occurrences; a single HTML attr referenced again inside JS strings is OK)
    ids = re.findall(r'data-design-id="([^"]+)"', text)
    # An id is a true duplicate only if it appears >1 as an actual attribute. We approximate
    # by checking the raw attribute pattern with a preceding space (attribute context).
    attr_ids = re.findall(r'\sdata-design-id="([^"]+)"', text)
    dupes = sorted({i for i in attr_ids if attr_ids.count(i) > 1})
    # Filter out ids that also appear inside a querySelector/getAttribute JS string form.
    real_dupes = []
    for d in dupes:
        # count occurrences that look like a JS selector usage
        js_uses = len(re.findall(rf'\[data-design-id=[\'"]{re.escape(d)}[\'"]\]', text))
        if attr_ids.count(d) - js_uses > 1:
            real_dupes.append(d)
    check(f"{fn} no duplicate design-ids", not real_dupes, f"dupes={real_dupes}")

    # onclick handlers must reference defined functions (adversarial)
    onclicks = set(re.findall(r'onclick="(\w+)\(', text))
    defined = set(re.findall(r'function\s+(\w+)\s*\(', text))
    # allow common inline/builtin patterns
    builtins = {"history", "window", "location"}
    undefined = sorted(o for o in onclicks if o not in defined and o not in builtins)
    check(f"{fn} onclick fns defined", not undefined, f"undefined={undefined}", hard=False)

    # no fabricated resume claims marker (guardrail): ensure no obviously invented metrics
    # (soft) — just report presence of the profile name for consistency
    check(f"{fn} references profile", ("Vikram" in text) or ("Vik" in text), "", hard=False)


# ---- Cross-link integrity (href to sibling screens must resolve) ----
existing = {p.name for p in SCREENS.glob("*.html")}
for fn in CORE_SCREENS:
    p = SCREENS / fn
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    hrefs = re.findall(r'href="([^"#]+\.html)"', text)
    broken = sorted({h for h in hrefs if Path(h).name not in existing})
    check(f"{fn} cross-links resolve", not broken, f"broken={broken}", hard=False)


# ---- canvas.json validity ----
canvas = ROOT / "design" / "canvas.json"
if canvas.exists():
    try:
        data = json.loads(canvas.read_text(encoding="utf-8"))
        check("canvas.json valid JSON", True)
        # count screens registered
        blob = json.dumps(data)
        for key in ["cover-letter-studio", "dashboard", "analytics"]:
            check(f"canvas.json registers {key}", key in blob, "", hard=False)
    except Exception as e:
        check("canvas.json valid JSON", False, str(e))
else:
    check("canvas.json exists", False)


# ---- canonical funnel 847 -> 412 -> 156 -> 23 -> 4 ----
FUNNEL = ["847", "412", "156", "23", "4"]
for fn in ["analytics.html", "dashboard.html"]:
    p = SCREENS / fn
    if p.exists():
        text = p.read_text(encoding="utf-8")
        present = all(n in text for n in FUNNEL)
        check(f"{fn} canonical funnel numbers", present, f"funnel={FUNNEL}", hard=False)


print("\n".join(report))
print("\n=== SUMMARY ===")
print(f"HARD FAILS: {len(hard_fail)}")
for f in hard_fail:
    print(f"  ✗ {f}")
print(f"SOFT WARNS: {len(soft_warn)}")
for w in soft_warn:
    print(f"  ! {w}")

sys.exit(1 if hard_fail else 0)
