// legal-privacy-page: the cookie statement on /legal says public pages set no
// cookie, use no Web Storage or IndexedDB and load nothing from other sites
// (CONSTRAINTS.md, "Legal"). This scan pins it: no Voter or core source names
// a browser storage API, and the document head loads nothing from another origin.
import { describe, expect, test } from "vitest";

import indexHtml from "../../../index.html?raw";

// Keys: "/src/..." for apps/web, "../../../../../packages/core/src/..." for core
// (the same files as admin-isolation.test.tsx, one directory deeper).
const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "../../../../../packages/core/src/**/*.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const isAdmin = (path: string) => path.startsWith("/src/admin/");
// Test files are not shipped; only real sources count.
const isTest = (path: string) => path.endsWith(".test.tsx") || path.startsWith("/src/test/");

const STORAGE_APIS = ["localStorage", "sessionStorage", "document.cookie", "indexedDB", "cookieStore"];

describe("no browser storage on public pages", () => {
  const voterSources = Object.entries(sources).filter(([path]) => !isAdmin(path) && !isTest(path));

  test("the scan sees Voter and core sources", () => {
    const paths = voterSources.map(([path]) => path);
    expect(paths).toContain("/src/main.tsx");
    expect(paths).toContain("/src/features/legal/LegalPage.tsx");
    expect(paths.some((p) => p.includes("packages/core/src/"))).toBe(true);
  });

  test.each(voterSources)("%s uses no cookie, Web Storage or IndexedDB", (_path, source) => {
    for (const api of STORAGE_APIS) {
      expect(source).not.toContain(api);
    }
  });

  test("index.html loads nothing from another origin", () => {
    expect(indexHtml).not.toMatch(/https?:\/\//);
  });
});
