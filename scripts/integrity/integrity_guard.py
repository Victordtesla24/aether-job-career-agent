#!/usr/bin/env python3
"""Integrity guard — blocks false-positive-producing practice from any environment.

Design rule: HIGH SIGNAL ONLY. A guard that cries wolf gets ignored, which is worse
than no guard. Every rule here targets an *executable construct* or a *config value*,
never prose. Domain words ("placeholder", "mock") in comments/docstrings are NOT
violations — this codebase legitimately discusses preventing fabrication.

Rules (exit 1 on any violation):
  R1  simulated/stubbed implementation in a shipped code path
  R2  dummy or test credentials / API keys as literals
  R3  fabricated-result modes enabled in a deployed environment (.env)
  R4  duplicate module basename (new file duplicating an existing one)
  R5  shipped source outside an approved directory
  R6  masked errors / suppressed warnings (bare except:pass, empty catch,
      @ts-nocheck, @ts-ignore, file-wide eslint-disable, blanket noqa/type:ignore)
  R7  disabled verification (skipped tests, continue-on-error, `|| true` after a
      test/lint/build command) — i.e. hiding a failure instead of fixing it

Waivers: scripts/integrity/waivers.txt as `path::rule::reason`. No reason = violation.
"""
from __future__ import annotations
import os, re, sys, pathlib, collections

ROOT = pathlib.Path(__file__).resolve().parents[2]
WAIVERS = ROOT / "scripts/integrity/waivers.txt"
EXCLUDE = {"negative_corpus", ".git","node_modules",".next",".venv","__pycache__",".turbo","dist","build",
           "coverage",".pytest_cache",".ruff_cache","uat","cleanup","evidence","screenshots",
           ".agent","site-packages"}
TESTISH = ("/test","/tests/","__tests__","/fixtures/","conftest.py",".test.",".spec.",
           "/e2e/","/mocks/","/__mocks__/","/evals/","integrity_guard.py")
SRC = {".py",".ts",".tsx",".js",".jsx",".mjs"}
APPROVED = ("apps/api/app","apps/api/scripts","apps/web/src","apps/web/e2e","packages",
            "scripts","ci","deploy",".github","design","ops")
# Framework config must sit at the app root — not a misplaced file.
CONFIG_OK = re.compile(r"^apps/(web|api)/[^/]*(config|env)[^/]*\.(ts|mjs|js|cjs|d\.ts)$")

def strip_comments(text: str, py: bool) -> str:
    """Blank out comments/strings so prose never triggers a rule."""
    if py:
        text = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', lambda m: "\n"*m.group(0).count("\n"), text)
        text = re.sub(r"(?m)#.*$", "", text)
    else:
        text = re.sub(r"/\*(?:.|\n)*?\*/", lambda m: "\n"*m.group(0).count("\n"), text)
        text = re.sub(r"(?m)//.*$", "", text)
    return text

# (regex, message, applies_to_code_only)
# NOTE: rules that depend on a COMMENT must be matched against raw text, because
# strip_comments() runs first. They are listed in R1_RAW.
R1 = [(r"\b(?:MOCK|SIMULATE|FAKE|STUB|DUMMY)[A-Z0-9_]*\s*(?::\s*[A-Za-z\[\]\.]+)?\s*=\s*(?:True|true|1)\b",
       "fabrication flag enabled in shipped code"),
      (r"\b[A-Z0-9_]*(?:MOCK|FAKE|STUB|DUMMY)[A-Z0-9_]*\s*(?::\s*[A-Za-z\[\]\.]+)?\s*=\s*(?:True|true|1)\b",
       "fabrication flag enabled in shipped code")]
R1_RAW = [(r"\breturn\s+(?:\[[^\]]*\]|\{[^}]*\}|None)\s*(?:#|//)\s*(?:stub|placeholder|todo|fake|mock)",
           "stubbed return value")]
R2 = [(r"sk-(?:test|dummy|fake|example)[A-Za-z0-9_-]{4,}", "test/dummy API key literal"),
      (r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'](?:changeme|password123|test123|dummy|fake|your[_-]?\w+[_-]?here)[\"']", "placeholder credential literal")]
# A suppression is acceptable ONLY when it states why, inline (noqa code, eslint
# rule name, or a trailing comment). Unexplained suppression is the violation.
R6 = [(r"except\s*(?:Exception|BaseException)?\s*(?:as\s+\w+)?\s*:(?![^\n]*(?:noqa:\s*\w|#\s*\S{3,}))(?!\s*\n\s*#)\s*(?:\n\s*)?pass\b",
       "broad except: pass with no stated reason — masks a real failure"),
      (r"catch\s*\([^)]*\)\s*\{\s*\}", "empty catch block — masks a real failure"),
      (r"@ts-nocheck", "@ts-nocheck disables type checking for the whole file"),
      (r"@ts-ignore(?![^\n]*--)", "@ts-ignore with no stated reason (use @ts-expect-error -- reason)"),
      (r"/\*\s*eslint-disable\s*\*/", "file-wide eslint-disable suppresses real lint errors"),
      (r"(?m)#\s*type:\s*ignore\s*$", "blanket '# type: ignore' (use a specific error code)"),
      (r"(?m)#\s*noqa\s*$", "blanket '# noqa' (use a specific rule code)")]
# Skips are allowed when conditional (skipif / a runtime guard) or when the reason
# is stated. An unconditional, unexplained skip is a hidden failure.
R7_SRC = [(r"\b(?:it|test|describe)\.skip\s*\(\s*[\"\x27`][^\"\x27`]*[\"\x27`]\s*,\s*(?:async\s*)?\(",
           "skipped test hides a failure (a disabled test is not a passing test)"),
          (r"\b(?:it|test|describe)\.skip\s*\(\s*\)", "skipped test hides a failure"),
          (r"\bx(?:it|describe)\s*\(", "disabled test (xit/xdescribe) hides a failure"),
          (r"@pytest\.mark\.skip\b(?!if)(?![^\n]*reason)", "@pytest.mark.skip with no reason= hides a failure")]
R7_CI = [
         (r"(?:pytest|pnpm\s+(?:run\s+)?(?:test|lint|build|type-check)|npm\s+(?:run\s+)?test)[^\n|;]*(?:\|\|\s*true|;\s*true)",
           "`|| true` / `; true` swallows a failing check"),
         (r"(?is)(?:not set|missing|unset|skip)[^\n]{0,120}\n[^\n]{0,120}exit\s+0",
           "`exit 0` after a skip condition marks an unrun suite as passing")]
ENV_FORBIDDEN = {"AETHER_LLM_MODE": {"replay","fixture","mock","fake"},
                 "AETHER_DISCOVERY_FIXTURES": {"1","true","yes","on"},
                 "AETHER_DISCOVERY_FIXTURE_DIR": {"*"},
                 "AETHER_DRY_RUN": {"1","true","yes","on"}}

def waivers():
    w = collections.defaultdict(set)
    if WAIVERS.exists():
        for i, ln in enumerate(WAIVERS.read_text().splitlines(), 1):
            ln = ln.strip()
            if not ln or ln.startswith("#"): continue
            parts = ln.split("::")
            if len(parts) != 3 or not parts[2].strip():
                print(f"waivers.txt:{i}: waiver without a reason -> {ln}"); sys.exit(1)
            w[parts[0].strip()].add(parts[1].strip())
    return w

def files():
    for dp, dn, fns in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in EXCLUDE]
        for fn in fns:
            f = pathlib.Path(dp)/fn
            yield f, str(f.relative_to(ROOT))

def main():
    W = waivers(); V = []
    def add(rel, rule, msg, line=None):
        if rule in W.get(rel, ()): return
        V.append((rule, rel, line, msg))

    for f, rel in files():
        testish = any(t in rel for t in TESTISH)
        if f.suffix in SRC:
            try: raw = f.read_text(encoding="utf-8", errors="replace")
            except OSError: continue
            code = strip_comments(raw, f.suffix == ".py")
            if not testish:
                for pat, msg in R1 + R2:
                    for m in re.finditer(pat, code):
                        add(rel, "R1" if (pat, msg) in R1 else "R2", msg, code[:m.start()].count("\n")+1)
                # comment-dependent rules must see the ORIGINAL text
                for pat, msg in R1_RAW:
                    for m in re.finditer(pat, raw):
                        add(rel, "R1", msg, raw[:m.start()].count("\n")+1)
                for pat, msg in R6:
                    src = raw if ("ts-" in pat or "eslint" in pat or "noqa" in pat or "type:" in pat) else code
                    for m in re.finditer(pat, src, re.M):
                        add(rel, "R6", msg, src[:m.start()].count("\n")+1)
                if not rel.startswith(APPROVED) and not CONFIG_OK.match(rel):
                    add(rel, "R5", "shipped source outside approved directories")
            for pat, msg in R7_SRC:
                for m in re.finditer(pat, code):
                    add(rel, "R7", msg, code[:m.start()].count("\n")+1)
        if rel.startswith(".github/workflows/") and f.suffix in {".yml",".yaml"}:
            try: raw = f.read_text(encoding="utf-8", errors="replace")
            except OSError: continue
            lines = raw.splitlines()
            for i, ln in enumerate(lines):
                if re.search(r"continue-on-error:\s*true", ln):
                    # Acceptable only when the surrounding lines say why (e.g. an
                    # explicitly non-blocking nightly job). Silent use is a violation.
                    ctx = " ".join(lines[max(0, i-6):i+1]).lower()
                    if not re.search(r"non-blocking|nightly|advisory|informational|known[- ]flaky", ctx):
                        add(rel, "R7", "continue-on-error with no stated reason lets a failing step pass", i+1)
            for pat, msg in R7_CI:
                for m in re.finditer(pat, raw):
                    add(rel, "R7", msg, raw[:m.start()].count("\n")+1)
        if (f.name == ".env" or f.name.startswith(".env.") or f.name.endswith(".env")) \
                and not f.name.endswith((".example", ".sample", ".template")):
            try: raw = f.read_text(errors="replace")
            except OSError: continue
            for i, ln in enumerate(raw.splitlines(), 1):
                ln = ln.strip()
                if ln.startswith("#") or "=" not in ln: continue
                k, v = ln.split("=", 1); k = k.strip(); v = v.strip().strip("\"'")
                bad = ENV_FORBIDDEN.get(k)
                if bad and (v in bad or ("*" in bad and v)):
                    add(rel, "R3", f"{k}={v} fabricates results in a deployed environment", i)

    # R4 — real duplication means near-identical CONTENT. Same basename across
    # layers (routers/auth.py vs middleware/auth.py) is deliberate architecture,
    # and Next.js REQUIRES a per-route error.tsx / loading.tsx.
    import hashlib
    byhash = collections.defaultdict(list)
    for f, rel in files():
        if f.suffix in SRC and not any(t in rel for t in TESTISH):
            try: body = f.read_text(encoding="utf-8", errors="replace")
            except OSError: continue
            norm = re.sub(r"\s+", " ", strip_comments(body, f.suffix == ".py")).strip()
            if len(norm) < 200:      # trivial/boilerplate files are not "duplication"
                continue
            byhash[hashlib.sha256(norm.encode()).hexdigest()].append(rel)
    for h, paths in byhash.items():
        if len(paths) > 1:
            add(paths[-1], "R4", f"byte-identical duplicate of {paths[0]} — reuse it instead of copying")

    print("="*70); print("INTEGRITY GUARD —", ROOT); print("="*70)
    if not V:
        print("PASS — no integrity violations."); return 0
    by = collections.Counter(v[0] for v in V)
    for rule in sorted(by):
        print(f"\n{rule}: {by[rule]}")
        for r, rel, line, msg in [x for x in V if x[0]==rule][:15]:
            print(f"  {rel}{':'+str(line) if line else ''}\n      {msg}")
    print(f"\nFAIL — {len(V)} violation(s). Fix, or add a justified waiver (path::rule::reason).")
    return 1

if __name__ == "__main__":
    sys.exit(main())
