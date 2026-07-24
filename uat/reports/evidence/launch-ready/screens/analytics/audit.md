# W-E screen audit — analytics

- Route: `/dashboard/analytics` (prod https://5cb5f0620.abacusai.cloud)
- Audited: 2026-07-24T00:54Z · headless Chromium (Playwright) · admin session
- Verdict: **FINDINGS**

## Results

| Check | Result |
|---|---|
| Console errors/warnings | 0 |
| Page errors | 0 |
| Failed requests | 0 |
| HTTP ≥400 responses | 0 |
| CLS on load | 0.1216 ⚠ exceeds 0.1 budget |
| axe serious/critical violations | 1 |
| Copy issues sampled (US dates / dev strings) | 1 |
| 360px horizontal scroll | no |
| Visible unnamed interactive controls | 0 |

### axe violations

- `dlitem` (serious, 14 nodes) — <dt> and <dd> elements must be contained by a <dl> — sample `.p-4.glass.rounded-2xl:nth-child(1) > dt`

## Findings

- axe dlitem (14 nodes: summary-grid <dt>/<dd> not wrapped in <dl>)
- CLS 0.122 > 0.1

All actionable items are tracked in the quality ledger (docs/delivery/MODELS-LIVE-GAPS.json, category `quality`, W-E wave).

## Screenshots (S3 — evidence archive)

- 1440px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/analytics-1440.png`
- 768px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/analytics-768.png`
- 360px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/analytics-360.png`

Raw audit data: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/results.json`
