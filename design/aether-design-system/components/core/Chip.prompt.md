Use `Chip` for row metadata and for filter pills.

```jsx
<Chip icon="fa-solid fa-location-dot">Melbourne · Hybrid</Chip>
<Chip tone="accent" mono>94% fit</Chip>
<Chip selected onClick={() => setFilter("all")}>All</Chip>
```

Set `mono` on anything numeric. `degraded` marks "produced nothing but did not fail"; never use `ok` for an unmeasured value.
