# W-E screen audit — settings

- Route: `/dashboard/settings` (prod https://5cb5f0620.abacusai.cloud)
- Audited: 2026-07-24T00:54Z · headless Chromium (Playwright) · admin session
- Verdict: **FINDINGS**

## Results

| Check | Result |
|---|---|
| Console errors/warnings | 0 |
| Page errors | 0 |
| Failed requests | 0 |
| HTTP ≥400 responses | 0 |
| CLS on load | 0.0377 |
| axe serious/critical violations | 1 |
| Copy issues sampled (US dates / dev strings) | 2 |
| 360px horizontal scroll | no |
| Visible unnamed interactive controls | 2 |

### axe violations

- `button-name` (critical, 2 nodes) — Buttons must have discernible text — sample `.bg-white\/15`

## Findings

- axe button-name critical (2 nodes: notification Toggle switch has no accessible name)
- US-format date (8/1/2026 renewal)
- billing price rendered as bare "$39 / month" (verify AUD label)

All actionable items are tracked in the quality ledger (docs/delivery/MODELS-LIVE-GAPS.json, category `quality`, W-E wave).

## Screenshots (S3 — evidence archive)

- 1440px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/settings-1440.png`
- 768px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/settings-768.png`
- 360px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/settings-360.png`

Raw audit data: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/results.json`
