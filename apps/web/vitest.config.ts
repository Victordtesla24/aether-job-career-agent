import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    globals: true,
    environment: "node",
    include: ["__tests__/**/*.test.ts", "src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
