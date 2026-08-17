Use `Section` for every card-level block of a workspace screen.

```jsx
<Section
  eyebrow="Pipeline"
  title="Agent activity"
  action={<Button tone="quiet" size="xs">View all</Button>}
  footnote="Last 30 runs — refreshed when the stream reports a change."
  accent
>
  {rows}
</Section>
```

Put disclosures in `footnote`, never in the title. `accent` is for a section that owns a live status.
