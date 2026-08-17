# Public site kit

Interactive recreation of Aether's public surface. Open `index.html`.

- **Pricing** — the real public landing page: gilded hero, monthly/annual switch, four ratified tiers (Free · Starter · Pro · Power) with GST-inclusive AUD prices and the GST breakdown on hover, the model-parity honesty note, and the three-point value band.
- **Sign in / Create account** — the auth card on the gilt glass surface, with plan context carried through from pricing, the forgot-password link and the deliberately-minor admin entry point.
- **Signed in** — hands off to the command-center kit.

Built from: `apps/web/src/app/pricing/page.tsx`, `app/login/page.tsx`, `components/PublicFooter.tsx`.

Prices and feature bullets are fixtures; the product reads `GET /api/billing/plans`.
