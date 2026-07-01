# Aether — Architecture & Delivery Decision Records (ADRs)

> One short entry per non-trivial decision. Keeps future sessions aligned and
> prevents re-litigating settled choices. Format below. Newest at the top.

**Template**
```
## ADR-NNN · <short title>
- Date: <ISO date> · Author: <session/agent id>
- Context: <what forced a decision>
- Decision: <what was chosen>
- Alternatives considered: <options + why rejected>
- Consequences: <trade-offs, follow-ups>
- Reversible? <yes/no + cost to reverse>
```

---

## ADR-001 · Use OpenRouter free/open-source models for all automated tests
- Date: 2026-07-02 · Author: bootstrap
- Context: Tests and validation need real LLM behavior without incurring paid cost or committing secrets.
- Decision: Route LLM calls through OpenRouter (OpenAI-compatible). Default test/validation models are the `:free` tier (DeepSeek v3, Llama 3.3 70B, Qwen 2.5 72B, Llama 3.1 8B), selected via env vars. Real key lives only in git-ignored `.env`.
- Alternatives considered: (a) Dummy/mocked keys only — rejected: doesn't validate real behavior; (b) Paid models in CI — rejected: cost + secret exposure.
- Consequences: CI replays recorded fixtures for speed/stability; a manual "live-openrouter" job checks drift. Model list is config, with fallback on rate-limit.
- Reversible? Yes — swap provider/models via env with low cost.

## ADR-002 · Strict TDD with vertical slices and PR-gated trunk
- Date: 2026-07-02 · Author: bootstrap
- Context: The program is large; we need continuity and quality across many sessions.
- Decision: Every change follows RED→GREEN→REFACTOR as small vertical slices, each committed with a slice ID, tracked in `PROGRESS.md`, and merged only via human-approved PRs. `main` stays releasable.
- Alternatives considered: Layered/big-bang delivery — rejected: poor demonstrability and high integration risk.
- Consequences: Slightly more overhead per change; far higher reliability and resumability.
- Reversible? Yes, but not recommended.
