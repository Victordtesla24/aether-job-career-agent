Use `PageHeader` once per screen, above everything else.

```jsx
<PageHeader
  title="Job Discovery"
  subtitle="Every role below was discovered by your agents and scored against your résumé."
  action={<Button tone="primary" icon="fa-solid fa-bolt">Run scout</Button>}
  controls={<SegmentedControl items={tabs} value={tab} onChange={setTab} ariaLabel="Market" idPrefix="market" />}
/>
```

Wrap it in `.atmos-hero` so the gold light sits behind the title band.
