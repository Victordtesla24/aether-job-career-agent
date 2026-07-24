# W-E screen audit — cover-letters

- Route: `/dashboard/cover-letters` (prod https://5cb5f0620.abacusai.cloud)
- Audited: 2026-07-24T00:54Z · headless Chromium (Playwright) · admin session
- Verdict: **FINDINGS**

## Results

| Check | Result |
|---|---|
| Console errors/warnings | 0 |
| Page errors | 0 |
| Failed requests | 0 |
| HTTP ≥400 responses | 0 |
| CLS on load | 0.4268 ⚠ exceeds 0.1 budget |
| axe serious/critical violations | 0 |
| Copy issues sampled (US dates / dev strings) | 2 |
| 360px horizontal scroll | no |
| Visible unnamed interactive controls | 0 |

## Findings

- US-format dates
- CLS 0.427 > 0.1 (skeleton→content swap)

All actionable items are tracked in the quality ledger (docs/delivery/MODELS-LIVE-GAPS.json, category `quality`, W-E wave).

## Screenshots (S3 — evidence archive)

- 1440px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/cover-letters-1440.png`
- 768px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/cover-letters-768.png`
- 360px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/cover-letters-360.png`

Raw audit data: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/results.json`

## Post-fix re-audit (wave 2, 2026-07-24)

Re-run of the full headless audit after the W-E fix waves (deploy = wave-2 commit): **0 console errors, 0 axe serious/critical violations, 0 unnamed controls, no 360 px horizontal scroll, 0 failed requests.** Residual: CLS 0.596 (skeleton→content swap on client-side data fetch; accepted, see QUALITY-WE-005).
