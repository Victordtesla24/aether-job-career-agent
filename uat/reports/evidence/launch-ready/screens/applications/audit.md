# W-E screen audit — applications

- Route: `/dashboard/applications` (prod https://5cb5f0620.abacusai.cloud)
- Audited: 2026-07-24T00:54Z · headless Chromium (Playwright) · admin session
- Verdict: **FINDINGS**

## Results

| Check | Result |
|---|---|
| Console errors/warnings | 0 |
| Page errors | 0 |
| Failed requests | 0 |
| HTTP ≥400 responses | 0 |
| CLS on load | 0.0114 |
| axe serious/critical violations | 1 |
| Copy issues sampled (US dates / dev strings) | 0 |
| 360px horizontal scroll | no |
| Visible unnamed interactive controls | 0 |

### axe violations

- `nested-interactive` (serious, 7 nodes) — Interactive controls must not be nested — sample `section[data-testid="kanban-column-ready"] > .gap-2\.5.flex-col > .cursor-pointer.hover\:border-white\/25[role="button"]`

## Findings

- axe nested-interactive (7 nodes: kanban card article role="button" wraps MoveMenu buttons)
- US-format dates (toLocaleDateString default locale)

All actionable items are tracked in the quality ledger (docs/delivery/MODELS-LIVE-GAPS.json, category `quality`, W-E wave).

## Screenshots (S3 — evidence archive)

- 1440px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/applications-1440.png`
- 768px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/applications-768.png`
- 360px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/applications-360.png`

Raw audit data: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/results.json`
