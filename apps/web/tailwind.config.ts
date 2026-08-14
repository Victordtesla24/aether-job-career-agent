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
        aether: {
          bg: "#0A0A0F",
          "bg-elevated": "#12121C",
          text: "#F4F4F8",
          muted: "#A0A0B8",
          "muted-dim": "#8B8BA3",
          coral: "#FF6B35",
          "coral-accent": "#F4715C",
          peach: "#FCD9CF",
          amber: "#F59E0B",
          indigo: "#4F46E5",
          violet: "#7C3AED",
          green: "#34D399",
          yellow: "#FBBF24",
        },
        // S-UI §2.1 — ADDITIVE surface ladder. Replaces ad-hoc
        // bg-white/[0.02|0.03|0.05] with four named ground levels so a KPI
        // strip, a card, a popover and a hovered row are no longer the same
        // colour. Every pre-existing `aether-*` value above is untouched, so
        // no existing class changes meaning.
        surface: {
          0: "#0A0A0F", // page ground
          1: "#101018", // card
          2: "#16161F", // raised card / popover / sticky header
          3: "#1C1C27", // hover / selected row
        },
        hairline: {
          DEFAULT: "rgba(255,255,255,0.07)", // default border
          strong: "rgba(255,255,255,0.13)", // hover / focus border
        },
        // S-UI §2.1 Rule D-1 (load-bearing): `state-neutral` and
        // `state-degraded` are the ONLY colours permitted for
        // "unavailable / degraded / not measured". A degraded value is never
        // `state-ok` green and never `state-danger` red — a working guard is
        // not a failure. This encodes the shipped coverLetterDegraded /
        // `available === false` honesty contracts as a colour law.
        state: {
          ok: "#34D399",
          warn: "#F59E0B",
          danger: "#F87171",
          info: "#818CF8",
          neutral: "#8B8BA3", // "no data" / "not measured" — NEVER green
          degraded: "#C4B5FD", // honest degrade: distinct from ok AND error
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
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
