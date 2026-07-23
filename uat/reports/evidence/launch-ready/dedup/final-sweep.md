# Final duplication sweep (post-wave-4, HEAD cb0186d, 2026-07-23T23:43Z)

## knip (apps/web, npx knip@5 --exports): exit 0 — 0 unused files, 0 unused exports, 0 unused types (raw: knip-final-post.json)

## jscpd (apps/web/src/lib + components/agents, --min-tokens 70): 1 clone remaining —
ProviderConfigModal.tsx[143:42-184:5] ~ TestRunModal.tsx[46:43-87:5] (42 lines, model-picker presentation block)
= DEDUP-028, adjudicated KEPT-WITH-REASON (a11y/testid regression risk, see wave-4-manifest.md).
