import type { Config } from "tailwindcss";

/**
 * Design tokens mirror `design/screens/dashboard.html` so the implemented shell
 * matches the approved wireframe. Colours are exposed under the `aether` palette
 * plus a few semantic aliases used across the dashboard.
 */
const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Aether Career Design System — obsidian & gilt. The palette below
        // REMAPS the legacy coral/indigo token VALUES to the new brand values
        // so every page that references `aether-*` (73 of them) rebrands at
        // once with zero markup change. Names are kept identical on purpose:
        //   coral  -> gilt (the single brand accent)
        //   indigo -> royal sapphire (agent-intelligence cue)
        //   violet -> sapphire-light readable value
        //   amber/yellow -> warm gilt values (copper carried by state-warn)
        //   green  -> jewel state-ok
        aether: {
          bg: "#08080A", // obsidian page ground (--ink-0)
          "bg-elevated": "#0F0F12", // card ground (--ink-1)
          text: "#F5F1E8", // warm parchment (--fg-1)
          muted: "rgba(245,241,232,0.62)", // --fg-2
          "muted-dim": "rgba(245,241,232,0.46)", // --fg-3
          coral: "#C9A84C", // --gold (brand accent)
          "coral-accent": "#D4B65C", // --gold-light
          peach: "#E8D5A3", // --gold-pale
          amber: "#C8873A", // copper (warn family)
          indigo: "#3E5A8C", // --sapphire
          violet: "#8FA8CE", // --sapphire-light (readable on obsidian)
          green: "#6FAF8D", // --state-ok
          yellow: "#E8D5A3", // --gold-pale
        },
        // S-UI §2.1 — ADDITIVE surface ladder. Replaces ad-hoc
        // bg-white/[0.02|0.03|0.05] with four named ground levels so a KPI
        // strip, a card, a popover and a hovered row are no longer the same
        // colour. Every pre-existing `aether-*` value above is untouched, so
        // no existing class changes meaning.
        surface: {
          0: "#08080A", // page ground (--ink-0)
          1: "#0F0F12", // card (--ink-1)
          2: "#16161A", // raised card / popover / sticky header (--ink-2)
          3: "#1E1E23", // hover / selected row (--ink-3)
        },
        hairline: {
          DEFAULT: "rgba(255,255,255,0.07)", // default border
          strong: "rgba(255,255,255,0.13)", // hover / focus border
        },
        // Gilt aliases — the single brand accent, exposed for opt-in use.
        gold: {
          DEFAULT: "#C9A84C",
          light: "#D4B65C",
          pale: "#E8D5A3",
          dark: "#B0923F",
        },
        sapphire: {
          DEFAULT: "#3E5A8C",
          light: "#8FA8CE",
        },
        burgundy: {
          DEFAULT: "#722F37",
          light: "#B9707A",
        },
        // S-UI §2.1 Rule D-1 (load-bearing): `state-neutral` and
        // `state-degraded` are the ONLY colours permitted for
        // "unavailable / degraded / not measured". A degraded value is never
        // `state-ok` green and never `state-danger` red — a working guard is
        // not a failure. This encodes the shipped coverLetterDegraded /
        // `available === false` honesty contracts as a colour law.
        state: {
          ok: "#6FAF8D", // jewel green — completed / connected / running
          warn: "#C8873A", // copper (never gold) — stalled / quota pressure
          danger: "#B9544B", // muted garnet — failed
          info: "#7C93BE", // advisory
          neutral: "#8C8A82", // "no data" / "not measured" — NEVER ok
          degraded: "#A08CB4", // honest degrade: distinct from ok AND danger
        },
      },
      fontFamily: {
        // AB Sans is the body/UI face; AB Marquee (all-caps stencil) is the
        // display face for page/card titles. JetBrains Mono is the data face.
        sans: ["'AB Sans'", "Inter", "system-ui", "sans-serif"],
        display: ["'AB Marquee'", "'Playfair Display'", "Georgia", "serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      borderRadius: {
        xs: "2px",
      },
      boxShadow: {
        "gilt-glow": "0 0 20px rgba(201,168,76,0.28)",
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(-6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
