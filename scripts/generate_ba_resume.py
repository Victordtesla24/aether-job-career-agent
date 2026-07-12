#!/usr/bin/env python3
"""Generate assets/resume/Vik_Resume_BA_Final.pdf — BA-first resume.

Content source : /home/ubuntu/Uploads/Vik_Resume_BA.pdf  (BA-angled roles/bullets)
Format contract: assets/resume/Vik_Resume_Final.pdf      (READ-ONLY — never modified)

Reproduces the format contract's layout programmatically:
US-Letter, two columns (left rail x=36..190, main x=230..576), peach title
panel (#FCD9CF), coral accents (#F4715C), dark headings (#222222), grey body
(#4D4D4D), coral square section icons, coral bullet glyphs, 3 pages, section
order CAREER OBJECTIVE -> CONTACT INFO -> WORK EXPERIENCE -> EDUCATION ->
SKILLS -> CERTIFICATIONS.

Anti-fabrication: every employer, date, metric, tool and certification below
is transcribed from the two source PDFs. Wording is strengthened for BA/PO
positioning only where the underlying claim exists in the sources.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# ---- palette / metrics lifted from the format contract -----------------
DARK = HexColor("#222222")      # name + section headings
BODY = HexColor("#4D4D4D")      # body text
META = HexColor("#6B6B6B")      # dates / locations
CORAL = HexColor("#F4715C")     # accents, bullets, subtitle
PEACH = HexColor("#FCD9CF")     # title panel
BOLD_DARK = HexColor("#2B2B2B")  # bold bullet lead-ins

PAGE_W, PAGE_H = letter          # 612 x 792
LX, LW = 36, 154                 # left rail
RX, RW = 230, 346                # main column
F, FB = "Helvetica", "Helvetica-Bold"

OUT = Path(__file__).resolve().parents[1] / "assets" / "resume" / "Vik_Resume_BA_Final.pdf"


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


class Writer:
    """Tiny top-down text cursor for one column of one page."""

    def __init__(self, c: canvas.Canvas, x: float, width: float, y: float):
        self.c, self.x, self.w, self.y = c, x, width, y

    def text(self, s: str, font: str, size: float, color, leading: float | None = None,
             indent: float = 0.0) -> None:
        leading = leading or size * 1.25
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        for line in wrap(s, font, size, self.w - indent):
            self.c.drawString(self.x + indent, self.y, line)
            self.y -= leading
    def gap(self, dy: float) -> None:
        self.y -= dy

    def section(self, title: str, size: float = 10.5) -> None:
        """Coral square icon + dark bold heading (contract style)."""
        self.c.setFillColor(CORAL)
        self.c.rect(self.x, self.y - 2.5, 11, 11, stroke=0, fill=1)
        self.c.setFont(FB, size)
        self.c.setFillColor(DARK)
        self.c.drawString(self.x + 17, self.y, title)
        self.y -= size * 1.9

    def bullet(self, s: str, size: float = 8.7, lead_in: str | None = None) -> None:
        leading = size * 1.32
        self.c.setFont(F, size + 1)
        self.c.setFillColor(CORAL)
        self.c.drawString(self.x + 1.5, self.y, "\u2022")
        indent = 11.0
        first = True
        if lead_in:
            # bold lead-in then normal remainder, wrapped together
            full = f"{lead_in} {s}".strip()
            lines = wrap(full, F, size, self.w - indent)
            for line in lines:
                if first and lead_in and line.startswith(lead_in.split()[0]):
                    # draw bold prefix portion of the first line
                    prefix = lead_in if stringWidth(lead_in, FB, size) <= self.w - indent else lead_in
                    if line.startswith(prefix):
                        self.c.setFont(FB, size)
                        self.c.setFillColor(BOLD_DARK)
                        self.c.drawString(self.x + indent, self.y, prefix)
                        rest = line[len(prefix):]
                        self.c.setFont(F, size)
                        self.c.setFillColor(BODY)
                        self.c.drawString(self.x + indent + stringWidth(prefix, FB, size), self.y, rest)
                    else:
                        self.c.setFont(F, size)
                        self.c.setFillColor(BODY)
                        self.c.drawString(self.x + indent, self.y, line)
                    first = False
                else:
                    self.c.setFont(F, size)
                    self.c.setFillColor(BODY)
                    self.c.drawString(self.x + indent, self.y, line)
                self.y -= leading
        else:
            self.c.setFont(F, size)
            self.c.setFillColor(BODY)
            for line in wrap(s, F, size, self.w - indent):
                self.c.drawString(self.x + indent, self.y, line)
                self.y -= leading
        self.y -= 2.5

    def role(self, title: str, employer: str, dates: str, loc: str) -> None:
        self.c.setFont(FB, 9.8)
        self.c.setFillColor(DARK)
        for line in wrap(title, FB, 9.8, self.w):
            self.c.drawString(self.x, self.y, line)
            self.y -= 12.4
        self.c.setFont(FB, 9.0)
        self.c.setFillColor(CORAL)
        self.c.drawString(self.x, self.y, employer)
        self.y -= 11.4
        self.c.setFont(F, 8.2)
        self.c.setFillColor(META)
        self.c.drawString(self.x, self.y, f"{dates}   |   {loc}")
        self.y -= 13.0


# ---------------------------------------------------------------- content
OBJECTIVE = (
    "15+ year Senior Business Analyst and Product Owner (Certified Scrum Master, CSM) "
    "specialising in requirements elicitation, gap analysis, end-to-end program delivery "
    "and enterprise transformation across the Financial Services and Telecommunications "
    "sectors. Proven track record of bridging technical engineering with executive "
    "strategy — guiding Azure/Cloud-based modernisations that cut delivery time by over "
    "30% and delivering mission-critical programs with multi-million dollar budgets. "
    "Core expertise: translating complex technical roadmaps into quantifiable business "
    "value, owning product backlogs and roadmaps, and aligning stakeholders from "
    "delivery squads to GM level. Deep hands-on grounding in Python, TypeScript and "
    "cloud-native infrastructure (Kubernetes/GCP/AWS) enables analysis that engineering "
    "teams trust, fostering agile culture and architectural alignment."
)

CONTACT = [
    "sarkar.vikram@gmail.com",
    "+61 433 224 556",
    "Melbourne, VIC, Australia",
    "linkedin.com/in/vikramd-profile",
    "github.com/Victordtesla24",
]

EDUCATION = [
    ("Master of Computer Science", "Monash University", "2010", "Melbourne", "Honors"),
    ("Bachelor of Engineering — Computer Science", "University of Melbourne", "2007", "Melbourne", None),
]

SKILLS_TECH = (
    "AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python, TypeScript, "
    "React/Next.js, Kubernetes, Docker, Terraform, GCP/AWS, Postgres/Supabase, "
    "Real-Time Telemetry."
)

SKILLS_CATEGORIES = [
    "Business Analysis, Requirements Elicitation, Gap Analysis, Product Ownership, "
    "Roadmap & Backlog Management, Stakeholder Alignment, Risk & Budget Management ($5M+), "
    "Technical Program Management, Agile/Scrum/SAFe.",
    "Enterprise Architecture, Data Architecture, MLOps, CI/CD, DevOps, Systems Thinking.",
    "Cross-functional Team Leadership, Servant Leadership, Coaching, Executive "
    "Communication, Vendor Management, Onsite/Offshore Model Coordination.",
]

CERTS = [
    ("Certified Scrum Master (CSM)", "Scrum Alliance"),
    ("Cloud/Data Certifications", "AWS/GCP (In progress)"),
]

# (title, employer, dates, location, [(lead_in, bullet)])  — all traceable to sources
ROLES_P1 = [
    (
        "Scrum Master / Project Manager", "Australian Taxation Office (ATO)",
        "March 2026 - Present", "Melbourne, VIC",
        [
            ("Agile Delivery Leadership:",
             "Lead end-to-end delivery for the Agile Kookaburras squad — one of eight squads "
             "on the Payday Super reform program (NTP & Distribution UI capabilities) — owning "
             "sprint cadence, PI Planning (PI 47-48), capacity management and executive status "
             "reporting."),
            ("Test Automation Strategy:",
             "Architected the program's COBOL/mainframe test-evidence automation covering 200+ "
             "SIT/E2E scenarios across all eight squads, cutting evidence effort from ~3 hours "
             "to ~15 minutes per scenario (~92% reduction) with a zero-new-approvals toolchain "
             "(REXX, SMF, SDSF, PCOMM, PowerShell, VBA)."),
            ("Delivery Recovery:",
             "Converted a mathematically infeasible SIT window — 75+ hours of manual evidence "
             "per team against 64 available hours — into an achievable plan through a six-day "
             "tiered harness build with a formal go/no-go gate and a four-level contingency "
             "ladder."),
            ("Governance & Change Management:",
             "Authored the executive change request re-baselining Payday Super test capacity, "
             "aligning eight squads and program leadership on scope, risk and schedule."),
        ],
    ),
]

ROLES_P2 = [
    (
        "Senior Delivery Lead / Technical Product Owner", "ANZ",
        "Sept 2017 - June 2025", "Melbourne, VIC",
        [
            ("AI/ML Strategy & Solutions (2022 - 2025):",
             "Led the technical delivery of AI solutions, including real-time WebSocket "
             "telemetry servers for 10k+ device concurrency, improving user response time by "
             "reducing P95 latency to under 200 ms."),
        ],
    ),
    (
        "AI/ML Strategy & Solutions Architect", "ANZ",
        "2017 - 2022", "Melbourne, VIC",
        [
            ("Agile Transformation & Program Management (2017 - 2022):",
             "Orchestrated the transformation of core banking platforms from monolithic to "
             "cloud-native (.NET/Azure), cutting end-to-end delivery time by >30% and reducing "
             "infrastructure costs by >15%."),
            ("Delivery Leadership:",
             "Directed a program portfolio valued at over $5M, leading 5+ cross-functional "
             "squads (up to 40 resources, including offshore teams) to deliver on-time, "
             "high-quality releases."),
            ("Architecture & Governance:",
             "Defined the technical vision and owned the product backlog for major platform "
             "modernisations, ensuring 100% compliance with enterprise architectural standards "
             "and risk models."),
            ("Stakeholder Alignment:",
             "Facilitated workshops for 40+ GMs and executives to align on strategy, improving "
             "decision-making efficiency and project clarity by >55%."),
        ],
    ),
    (
        "Senior Project Manager & Business Analyst", "National Australia Bank (NAB)",
        "Nov 2016 - Sept 2017", "Melbourne, VIC",
        [
            (None,
             "Managed the delivery stream for a critical risk and compliance program, ensuring "
             "100% regulatory adherence for major data initiatives."),
            (None,
             "Conducted deep-dive business analysis, translating complex regulatory "
             "requirements into actionable technical specifications for development teams."),
        ],
    ),
    (
        "Lead Business Analyst", "Microsoft Inc.",
        "Oct 2015 - Oct 2016", "Sydney, NSW",
        [
            (None,
             "Executed a comprehensive gap analysis for Azure ML telemetry, delivering 10 key "
             "insights that enhanced system reliability by 15% and decreased incident MTTR by "
             "10%."),
            (None,
             "Spearheaded initiatives to align DevOps strategies with overall IT objectives, "
             "achieving 95% alignment with enterprise architecture standards."),
        ],
    ),
]

ROLES_P3 = [
    (
        "Business Analyst / Project Coordinator", "Telstra",
        "Nov 2014 - Oct 2015", "Melbourne, VIC",
        [
            (None,
             "Developed customer journey scorecards and streamlined Jira requirements for core "
             "delivery teams, improving delivery efficiency by 20% and operational clarity by "
             "15%."),
        ],
    ),
    (
        "Senior Business Analyst", "InfoCentric",
        "Aug 2011 - Nov 2014", "Melbourne, VIC",
        [
            (None,
             "Delivered analytics and Business Intelligence (BI) projects, boosting client "
             "customer engagement by 20% and automating regulatory reporting workflows to "
             "achieve 100% accuracy."),
        ],
    ),
    (
        "Developer Support / Software Testing / Analyst", "MYOB",
        "May 2010 - Aug 2011", "Melbourne, VIC",
        [
            (None,
             "Optimized data processing workflows through ePAL implementation, improving "
             "efficiency by 30% and reducing reporting time by 90% for financial data sets."),
        ],
    ),
    (
        "Independent AI Consulting & Upskilling", "Independent",
        "June 2025 - Feb 2026", "Melbourne, VIC",
        [
            ("JIRA Analytics Dashboard:",
             "Architected and developed a Next.js + Supabase analytics application to expose "
             "sprint velocity metrics and generate LLM-powered retrospective insights and "
             "sprint plans."),
            ("Public-Key Server:",
             "Built a robust, production-grade Node.js/Express service for distributing PEM "
             "keys for fleet API signing, achieving 100% test coverage (Mocha/Chai)."),
            ("Relationship Timeline Visualisation:",
             "Developed a React/TypeScript visualisation tool featuring D3 event arcs for "
             "showcasing dynamic customer journey interactions."),
            ("LLM Evaluation Stack:",
             "Stood up an end-to-end Langfuse + Phoenix evaluation stack to score "
             "hallucination, latency and cost across high-volume daily LLM generations, "
             "reducing error budget breaches by 38% in a simulated production environment."),
        ],
    ),
]


def draw_title_block(c: canvas.Canvas) -> None:
    c.setFont(FB, 20.2)
    c.setFillColor(DARK)
    c.drawString(LX, PAGE_H - 52, "VIKRAM")
    c.drawString(LX, PAGE_H - 76, "DESHPANDE")
    c.setFillColor(PEACH)
    c.rect(LX, PAGE_H - 180, LW, 82, stroke=0, fill=1)
    c.setFont(FB, 12.0)
    c.setFillColor(CORAL)
    y = PAGE_H - 118
    for line in ["Senior Business", "Analyst / Product", "Owner"]:
        c.drawString(LX + 9, y, line)
        y -= 15.5
    c.setFont(F, 9.0)
    c.setFillColor(BODY)
    c.drawString(LX + 9, y - 2, "(Technical Delivery Lead)")


def build() -> None:
    c = canvas.Canvas(str(OUT), pagesize=letter)
    c.setTitle("Vikram Deshpande — Senior Business Analyst / Product Owner")
    c.setAuthor("Vikram Deshpande")

    # ---------- page 1 ----------
    draw_title_block(c)
    left = Writer(c, LX, LW, PAGE_H - 208)
    left.section("CONTACT INFO")
    for item in CONTACT:
        left.text(item, F, 8.6, BODY, leading=13.2)
    left.gap(14)
    left.section("EDUCATION")
    for degree, school, year, city, honors in EDUCATION:
        left.text(degree, FB, 9.4, DARK, leading=11.8)
        left.text(school, FB, 9.0, CORAL, leading=11.4)
        left.text(f"{year}  |  {city}", F, 8.2, META, leading=11.0)
        if honors:
            left.text(honors, F, 8.2, META, leading=11.0)
        left.gap(6)
    left.gap(8)
    left.section("SKILLS")
    left.text(SKILLS_TECH, F, 8.6, BODY, leading=12.2)

    right = Writer(c, RX, RW, PAGE_H - 48)
    right.section("CAREER OBJECTIVE", size=11.2)
    right.text(OBJECTIVE, F, 8.9, BODY, leading=12.6)
    right.gap(14)
    right.section("WORK EXPERIENCE", size=11.2)
    for title, emp, dates, loc, bullets in ROLES_P1:
        right.role(title, emp, dates, loc)
        for lead, b in bullets:
            right.bullet(b, lead_in=lead)
        right.gap(6)
    c.showPage()

    # ---------- page 2 ----------
    left = Writer(c, LX, LW, PAGE_H - 48)
    left.section("SKILLS")
    for cat in SKILLS_CATEGORIES:
        left.bullet(cat, size=8.4)
        left.gap(4)

    right = Writer(c, RX, RW, PAGE_H - 48)
    for title, emp, dates, loc, bullets in ROLES_P2:
        right.role(title, emp, dates, loc)
        for lead, b in bullets:
            right.bullet(b, lead_in=lead)
        right.gap(8)
    c.showPage()

    # ---------- page 3 ----------
    left = Writer(c, LX, LW, PAGE_H - 48)
    left.section("CERTIFICATIONS")
    for cert, issuer in CERTS:
        left.bullet(f"{cert} — {issuer}", size=8.6)
        left.gap(4)

    right = Writer(c, RX, RW, PAGE_H - 48)
    for title, emp, dates, loc, bullets in ROLES_P3:
        right.role(title, emp, dates, loc)
        for lead, b in bullets:
            right.bullet(b, lead_in=lead)
        right.gap(8)
    c.showPage()

    c.save()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
