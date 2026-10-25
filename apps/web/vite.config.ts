import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": backend,
      "/health": backend,
    },
  },
  test: {
    name: "web",
    environment: "jsdom",
    include: ["src/**/*.test.tsx"],
    setupFiles: ["src/test/setup.ts"],
    // Vitest empties every CSS import by default; let `?raw` imports through so
    // src/ui/design-tokens.test.tsx can read the real stylesheets.
    css: { include: [/[?&]raw(?:&|$)/] },
  },
});
