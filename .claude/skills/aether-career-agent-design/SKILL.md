---
name: aether-career-agent-design
description: Default design system for Aether CareerAI Agent. Use before generating any UI, email, markdown, HTML, SVG, chart, or document. Obsidian and gilt.
user-invocable: true
---

# Aether Career agent design skill

The full system is vendored at **`design/aether-design-system/`** (Claude zip).

**Required first read:** `design/aether-design-system/readme.md`

Then:

- Tokens: `design/aether-design-system/tokens/colors.css` (gilt `#C9A84C`, ink `#08080A`, sapphire `#3E5A8C`)
- Components: `design/aether-design-system/components/`
- UI kits: `design/aether-design-system/ui_kits/`
- Product restatement: `design/DESIGN.md`
- Email: `apps/api/app/services/email_branding.py`
- Generated markdown/HTML: `apps/api/app/services/branded_artefacts.py` or `design/templates/artefact.html`

**Forbidden:** coral `#FF6B35`, indigo `#4F46E5`, emoji, Inter as the brand face, gold used as a status colour.

If the user invokes this skill without other guidance, ask what artefact they need and output HTML against the tokens, or production code in the existing app surfaces — never a parallel palette.
