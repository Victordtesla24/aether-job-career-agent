"""Deterministic portfolio-page fixture for the career-data service (GAP-P4-047).

Mirrors the shape of a real Next.js-rendered portfolio page — ``<title>``, a
meta description, a schema.org ``Person`` JSON-LD block, and server-rendered
visible text — so the HTML parser can be exercised offline without any network
call. This is synthetic sample test data (the purpose of a fixture); it is NOT
scraped from any live site and must not be treated as real portfolio content.
"""
from __future__ import annotations

#: A distinctive skill token ("Kubernetes") that appears in the portfolio text
#: but NOT in the base resume — used to prove career evidence widens the
#: tailoring/cover-letter anti-fabrication corpus.
PORTFOLIO_HTML = """<!DOCTYPE html><html lang="en"><head>
<meta charSet="utf-8"/>
<title>Sample Candidate — Delivery Lead &amp; Solutions Architect</title>
<meta name="description" content="Delivery lead and solutions architect based in Melbourne."/>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Person","name":"Sample Candidate",
"jobTitle":"Delivery Lead","worksFor":{"@type":"Organization","name":"Sample Org"},
"sameAs":["https://github.com/sample-candidate"]}
</script>
<style>.hero{color:red}</style>
<script>window.__DATA__ = {secret: "should-not-appear"};</script>
</head><body>
<header><nav>Home About Work Contact</nav></header>
<main>
<h1>Hello, I'm Sample Candidate</h1>
<p>Delivery lead and solutions architect. I design and ship real-time platforms
on Kubernetes with a focus on measurable outcomes.</p>
<section><h2>Selected work</h2>
<p>Led a program that cut evidence effort by 40% across delivery squads.</p>
</section>
</main>
<noscript>Enable JavaScript to view telemetry.</noscript>
</body></html>"""


def portfolio_html_fixture() -> str:
    """The raw HTML a portfolio fetch would return."""
    return PORTFOLIO_HTML
