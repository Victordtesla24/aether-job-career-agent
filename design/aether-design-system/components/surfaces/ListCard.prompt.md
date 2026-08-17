Use `ListCard` for every selectable row in a list or two-pane browser.

```jsx
<ListCard selected={id === activeId} onClick={() => setActive(id)}>
  <h4 className="type-label">Senior Data Analyst</h4>
  <p className="type-meta">Telstra · Melbourne</p>
</ListCard>
```

Pass `interactive={false}` for a static card. Selection state must always be a gold rail plus the elevation step — never a colour fill.
