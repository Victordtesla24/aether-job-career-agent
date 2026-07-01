---
name: "Aether — Autonomous AI Career Agent"
colors:
  primary: "#FF6B35"
  secondary: "#4F46E5"
  accent: "#F59E0B"
  neutral: "#8A8AA3"
  background: "#0A0A0F"
  backgroundAlt: "#12121C"
  surface: "#16161F"
  surfaceRaised: "#1C1C29"
  border: "#26263A"
  textPrimary: "#F4F4F8"
  textSecondary: "#A0A0B8"
  textMuted: "#6B6B82"
  success: "#34D399"
  warning: "#FBBF24"
  error: "#F87171"
  info: "#60A5FA"
typography:
  display:
    fontFamily: Inter
    fontSize: 2.5rem
    fontWeight: 700
  heading:
    fontFamily: Inter
    fontSize: 1.375rem
    fontWeight: 600
  body:
    fontFamily: Inter
    fontSize: 0.9375rem
    fontWeight: 400
  label:
    fontFamily: Inter
    fontSize: 0.75rem
    fontWeight: 500
  mono:
    fontFamily: "JetBrains Mono"
    fontSize: 0.8125rem
    fontWeight: 400
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  full: "9999px"
---

## Overview
Aether is an autonomous AI career agent's command center — a premium dark-mode control room that should feel alive, intelligent, and calm. Target audience: ambitious professionals who delegate their job search to AI agents and want oversight without noise. Emotional intent: confident, futuristic, trustworthy. The bar is Vercel Dashboard × Linear × Anthropic Console.

## Color usage
Deep near-black canvas (#0A0A0F) with a subtle vertical gradient toward #12121C / a hint of indigo (#1a1a2e). Surfaces are glassmorphic: semi-transparent dark panels (rgba white 3-6%) with `backdrop-blur` and hairline borders (#26263A). Coral #FF6B35 is the SINGLE primary action / brand signal — used on primary CTAs, active nav, key metrics, and the agent's live pulse. Electric indigo #4F46E5 is the secondary accent for AI/agent intelligence cues, links, and data viz. Status colors (success green, warning amber, error red) whisper — used only in badges and small indicators. Never flood a section with coral or indigo; they are punctuation.

## Typography
Inter throughout for UI; JetBrains Mono for data — timestamps, IDs, scores, salary figures, agent logs. Establish clear hierarchy: `text-4xl`/`font-bold` for hero numbers and page titles, `text-lg`/`font-semibold` for section headings, `text-sm` for body, `text-xs`/`uppercase`/`tracking-wide` for labels. One display weight per screen.

## Layout
Persistent 248px left sidebar + top bar shell across desktop app screens. Generous 24-40px section padding, 16-24px gaps in grids. Content max density is medium — cards breathe. Glass cards use `rounded-2xl`, `border border-white/8`, `bg-white/[0.03]`, `backdrop-blur-xl`, subtle `shadow-2xl shadow-black/40`. Hover states lift cards (`hover:border-white/15`, subtle coral/indigo glow). Micro-interactions implied via transitions.

## Do's and Don'ts
- Do: use glassmorphism — translucent panels over the gradient canvas with backdrop blur and hairline borders.
- Do: reserve coral #FF6B35 for the primary action and brand pulse; use indigo #4F46E5 for AI/agent cues.
- Do: use JetBrains Mono for every number, score, timestamp, and ID.
- Do: use soft glows (coral/indigo at low opacity) sparingly to signal live agent activity.
- Don't: use pure black (#000) or flat gray cards without blur/border.
- Don't: flood sections with gradient fills or use more than the two accents.
- Don't: use emoji as icons — use Font Awesome 6.
- Don't: put drop shadows on every element; use depth to signal hierarchy only.
