Use `StatBlock` for the KPI strip at the top of a workspace screen.

```jsx
<StatBlock label="Active applications" value="42" delta={2} note="+3 this week" />
<StatBlock label="Interview rate" value="18" unit="%" note="7 of 39 applied" />
<StatBlock label="AI confidence" value={null} note="no scored roles yet" />
```

Four tiles per strip is the house rhythm. Pass `value={null}` rather than `0` when nothing has been measured.
