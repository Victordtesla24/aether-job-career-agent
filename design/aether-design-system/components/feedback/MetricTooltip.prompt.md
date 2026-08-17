Use `MetricTooltip` on any figure whose basis is not self-evident.

```jsx
<MetricTooltip
  value="18%"
  tooltip="Share of your applications that progressed to at least one interview (Application → Interview %)."
/>
```

Inside a `StatBlock`, pass it as the child so the raised unit still renders beside it.
