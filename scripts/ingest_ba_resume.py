"""Ingest the BA resume PDF into Aether via its own API (POST /resumes).

Usage:
    python scripts/ingest_ba_resume.py <api_base_url> <jwt_token>

Extracts full text from assets/resume/Vik_Resume_BA_Final.pdf, derives a
format hash from the PDF bytes, and registers it as a new root resume so it
appears in Resume Studio and is selectable for tailoring runs.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import fitz  # PyMuPDF

PDF = Path(__file__).resolve().parents[1] / "assets" / "resume" / "Vik_Resume_BA_Final.pdf"
LABEL = "BA Resume — Senior Business Analyst / Product Owner"


def main() -> None:
    api_base, token = sys.argv[1].rstrip("/"), sys.argv[2]
    doc = fitz.open(PDF)
    raw_text = "\n".join(page.get_text() for page in doc)
    format_hash = hashlib.sha256(PDF.read_bytes()).hexdigest()[:16]
    payload = {
        "label": LABEL,
        "raw_text": raw_text,
        # Canonical contact block from the portfolio site
        # (https://forgotten-mistory.web.app/ — mailto/tel links).
        "contact": {
            "name": "Vikram Deshpande",
            "phone": "+61 433 224 556",
            "email": "sarkar.vikram@gmail.com",
            "location": "Melbourne, VIC, Australia",
            "github": "github.com/Victordtesla24",
            "linkedin": "linkedin.com/in/vikramd-profile",
        },
        "format_hash": format_hash,
    }
    req = urllib.request.Request(
        f"{api_base}/api/resumes",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "curl/8.5.0"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
        print(json.dumps({"status": resp.status, "resume": body}, indent=2))


if __name__ == "__main__":
    main()
