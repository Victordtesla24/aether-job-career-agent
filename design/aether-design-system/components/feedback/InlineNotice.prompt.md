Use `InlineNotice` instead of a bespoke coloured `div` for any inline message.

```jsx
<InlineNotice tone="danger">Couldn't load the approval queue — request failed.</InlineNotice>
<InlineNotice tone="degraded" title="Nothing produced">
  The cover-letter agent returned no draft. Nothing was sent.
</InlineNotice>
<InlineNotice tone="warn" onDismiss={dismiss}>92 of 100 runs used this period.</InlineNotice>
```

Say what is true and what happens next; never dress a failure as a success.
