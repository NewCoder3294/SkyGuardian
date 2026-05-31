import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// jsdom so component/hook tests have a DOM; `automatic` JSX so .tsx tests don't
// need an explicit React import. The existing pure-logic specs run fine here too.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
