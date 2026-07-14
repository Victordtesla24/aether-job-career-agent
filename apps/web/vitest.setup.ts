// Extends vitest's `expect` with the @testing-library/jest-dom matchers
// (toBeInTheDocument, toHaveAttribute, toHaveTextContent, ...) used by the
// component-level page tests (e.g. src/app/signup/__tests__/page.test.tsx).
// Safe to load for every test file: it only adds matchers and is a no-op for
// suites (node-environment unit tests) that never touch the DOM.
import "@testing-library/jest-dom/vitest";
