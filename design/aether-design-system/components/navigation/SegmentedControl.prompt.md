Use `SegmentedControl` for any 2–6 way switch between views of the same screen.

```jsx
<SegmentedControl
  ariaLabel="Applications view"
  idPrefix="view"
  value={view}
  onChange={setView}
  items={[
    { value: "board", label: "Board", icon: "fa-solid fa-table-columns", count: 42 },
    { value: "flow", label: "Flow", icon: "fa-solid fa-diagram-project" }
  ]}
/>
```

The strip wraps at narrow widths — it never scrolls sideways, so no tab can be clipped.
