Use `Button` for every actionable control; `tone="primary"` is the one gold-filled action per surface.

```jsx
<Button tone="primary" size="md" icon="fa-solid fa-bolt">Run discovery</Button>
<Button tone="outline">View all</Button>
<Button tone="quiet" size="xs">Dismiss</Button>
<div style={{ display: "flex", gap: 8 }}>
  <Button tone="ok" block>Approve</Button>
  <Button tone="danger" block>Reject</Button>
</div>
```

Tones: `primary` (gold gradient, dark label), `outline` (gold hairline), `neutral`, `quiet`, and the four state tones `ok` / `warn` / `danger` / `info`. Sizes `xs` / `sm` / `md` / `lg` — `lg` is for public-site CTAs only. Labels stay ALL CAPS; never put two `primary` buttons on one screen.
