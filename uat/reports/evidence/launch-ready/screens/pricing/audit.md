# W-E screen audit — pricing

- Route: `/pricing` (prod https://5cb5f0620.abacusai.cloud)
- Audited: 2026-07-24T00:54Z · headless Chromium (Playwright) · admin session
- Verdict: **FINDINGS**

## Results

| Check | Result |
|---|---|
| Console errors/warnings | 0 |
| Page errors | 0 |
| Failed requests | 1 |
| HTTP ≥400 responses | 0 |
| CLS on load | 0.0178 |
| axe serious/critical violations | 2 |
| Copy issues sampled (US dates / dev strings) | 1 |
| 360px horizontal scroll | no |
| Visible unnamed interactive controls | 0 |

### axe violations

- `color-contrast` (serious, 1 nodes) — Elements must meet minimum color contrast ratio thresholds — sample `.text-aether-indigo`
- `link-in-text-block` (serious, 1 nodes) — Links must be distinguishable without relying on color — sample `.text-aether-indigo`

### Failed requests

- GET https://5cb5f0620.abacusai.cloud/privacy-policy?_rsc=6i8d7 :: net::ERR_ABORTED

## Findings

- axe color-contrast + link-in-text-block (footer login link text-aether-indigo on dark bg)

All actionable items are tracked in the quality ledger (docs/delivery/MODELS-LIVE-GAPS.json, category `quality`, W-E wave).

## Screenshots (S3 — evidence archive)

- 1440px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/pricing-1440.png`
- 768px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/pricing-768.png`
- 360px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/pricing-360.png`

Raw audit data: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/results.json`
