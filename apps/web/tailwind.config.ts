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
          amber: "#F59E0B",
          indigo: "#4F46E5",
          violet: "#7C3AED",
          green: "#34D399",
          yellow: "#FBBF24",
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
