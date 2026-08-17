Use `StatusBadge` for any state a row, run or artifact is in.

```jsx
<StatusBadge tone="ok" dot live>Running</StatusBadge>
<StatusBadge tone="neutral">Not measured</StatusBadge>
<StatusBadge tone="degraded">Produced nothing</StatusBadge>
```

Never encode a state in colour alone, never animate a non-live state, and never use `neutral` where a measurement exists (or `ok` where one does not).
