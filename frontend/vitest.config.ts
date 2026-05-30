import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Pure-logic unit tests (no DOM): URL/config helpers that keep the dashboard
// pointed at the same brain the mobile app and backend use.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
