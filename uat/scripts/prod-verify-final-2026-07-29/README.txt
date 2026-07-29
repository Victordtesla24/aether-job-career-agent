These four Playwright harnesses produced the item-1/4/5/6/7 evidence in
uat/reports/evidence/prod-verify-final-2026-07-29/. They import @playwright/test, which is
installed only under apps/web, so ESM resolution requires running them from there:

  cp uat/scripts/prod-verify-final-2026-07-29/prod-verify-sweep.mjs apps/web/ && cd apps/web && node prod-verify-sweep.mjs

All four are read-only against production except that they log in as admin.
