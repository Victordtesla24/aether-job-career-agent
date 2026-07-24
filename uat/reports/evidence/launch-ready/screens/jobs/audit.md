# W-E screen audit — jobs

- Route: `/dashboard/jobs` (prod https://5cb5f0620.abacusai.cloud)
- Audited: 2026-07-24T00:54Z · headless Chromium (Playwright) · admin session
- Verdict: **FINDINGS**

## Results

| Check | Result |
|---|---|
| Console errors/warnings | 0 |
| Page errors | 0 |
| Failed requests | 0 |
| HTTP ≥400 responses | 0 |
| CLS on load | 0.136 ⚠ exceeds 0.1 budget |
| axe serious/critical violations | 2 |
| Copy issues sampled (US dates / dev strings) | 1 |
| 360px horizontal scroll | no |
| Visible unnamed interactive controls | 0 |

### axe violations

- `nested-interactive` (serious, 12 nodes) — Interactive controls must not be nested — sample `.border-aether-coral\/40`
- `scrollable-region-focusable` (serious, 2 nodes) — Scrollable region must have keyboard access — sample `.overflow-x-auto`

## Findings

- axe nested-interactive (12 nodes: job card article role="button" wraps checkbox/buttons)
- axe scrollable-region-focusable (2 nodes: .overflow-x-auto)
- US-format dates absent here but CLS 0.136 > 0.1

All actionable items are tracked in the quality ledger (docs/delivery/MODELS-LIVE-GAPS.json, category `quality`, W-E wave).

## Screenshots (S3 — evidence archive)

- 1440px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/jobs-1440.png`
- 768px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/jobs-768.png`
- 360px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/jobs-360.png`

Raw audit data: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/results.json`
