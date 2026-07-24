# W-E screen audit — email

- Route: `/dashboard/email` (prod https://5cb5f0620.abacusai.cloud)
- Audited: 2026-07-24T00:54Z · headless Chromium (Playwright) · admin session
- Verdict: **FINDINGS**

## Results

| Check | Result |
|---|---|
| Console errors/warnings | 0 |
| Page errors | 0 |
| Failed requests | 0 |
| HTTP ≥400 responses | 0 |
| CLS on load | 0.0061 |
| axe serious/critical violations | 0 |
| Copy issues sampled (US dates / dev strings) | 2 |
| 360px horizontal scroll | YES ⚠ |
| Visible unnamed interactive controls | 0 |

## Findings

- 360px viewport horizontally scrollable (email grid / inbox-account chip overflow)
- US-format dates in list metadata

All actionable items are tracked in the quality ledger (docs/delivery/MODELS-LIVE-GAPS.json, category `quality`, W-E wave).

## Screenshots (S3 — evidence archive)

- 1440px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/email-1440.png`
- 768px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/email-768.png`
- 360px: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/email-360.png`

Raw audit data: `s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/results.json`

## Post-fix re-audit (wave 2, 2026-07-24)

Re-run of the full headless audit after the W-E fix waves (deploy = wave-2 commit): **0 console errors, 0 axe serious/critical violations, 0 unnamed controls, no 360 px horizontal scroll, 0 failed requests.** Residual 'US date' hits are inside user email body content (real email data), not app copy.
