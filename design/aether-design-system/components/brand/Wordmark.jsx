import React from "react";

const SIZES = { sm: { mark: 28, name: 13, tag: 9 }, md: { mark: 36, name: 16, tag: 10 }, lg: { mark: 56, name: 24, tag: 11 } };

/** The Aether lockup: the real gold mark, the name in the display face. */
export function Wordmark({ size = "md", variant = "full", tagline = "Job & Career Agent", src = "assets/aether-mark.png", className = "", style }) {
  const s = SIZES[size] || SIZES.md;
  return (
    <span className={className} style={{ display: "inline-flex", alignItems: "center", gap: size === "lg" ? 16 : 11, ...style }}>
      <img
        src={src}
        alt="Aether"
        width={s.mark}
        height={s.mark}
        style={{ width: s.mark, height: s.mark, borderRadius: "var(--radius-md)", border: "1px solid var(--gold-muted)", flexShrink: 0, display: "block" }}
      />
      {variant === "full" ? (
        <span style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: s.name,
              fontWeight: 500,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              lineHeight: 1,
              color: "var(--text-primary)"
            }}
          >
            Aether
          </span>
          {tagline ? (
            <span style={{ fontFamily: "var(--font-body)", fontSize: s.tag, letterSpacing: "0.18em", textTransform: "uppercase", color: "var(--gold)", opacity: 0.85, lineHeight: 1 }}>
              {tagline}
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}
