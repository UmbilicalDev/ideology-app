import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      // Two pages: the Voter app and the Operator admin page (feedback-admin),
      // emitted as dist/index.html and dist/admin/index.html. The Voter entry
      // never imports src/admin/, so its bundle holds no admin code.
      input: {
        main: "index.html",
        admin: "admin/index.html",
      },
    },
  },
  server: {
    proxy: {
      "/api": backend,
      "/health": backend,
      "/admin/api": backend,
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
