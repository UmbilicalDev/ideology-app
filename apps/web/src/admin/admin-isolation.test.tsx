// feedback-admin Decision 13 and Scenario 13 (isolation): the admin page is a
// separate entry; no Voter source imports src/admin/ or names "/admin"; the
// admin document head is noindex with the same-origin icons.
import { describe, expect, test } from "vitest";

import adminIndexHtml from "../../admin/index.html?raw";

// Keys: "/src/..." for apps/web, "../../../../packages/core/src/..." for core.
const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "../../../../packages/core/src/**/*.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const isAdmin = (path: string) => path.startsWith("/src/admin/");
// Test files are not shipped; only real sources count.
const isTest = (path: string) => path.endsWith(".test.tsx") || path.startsWith("/src/test/");

describe("admin isolation", () => {
  test("the scan sees both Voter and admin sources", () => {
    const paths = Object.keys(sources);
    expect(paths).toContain("/src/main.tsx");
    expect(paths).toContain("/src/app/App.tsx");
    expect(paths).toContain("/src/admin/main.tsx");
    expect(paths.some((p) => p.includes("packages/core/src/"))).toBe(true);
  });

  test.each(Object.entries(sources).filter(([path]) => !isAdmin(path) && !isTest(path)))(
    "%s neither imports src/admin/ nor names /admin",
    (_path, source) => {
      expect(source).not.toMatch(/from\s+["'][^"']*\/admin\//);
      expect(source).not.toMatch(/import\(\s*["'][^"']*\/admin\//);
      expect(source).not.toContain("/admin");
    },
  );

  test("only the admin entry passes the browser's fetch to the admin client", () => {
    const users = Object.entries(sources)
      .filter(([, source]) => source.includes("createAdminApiClient({ fetch: (url, init) => window.fetch"))
      .map(([path]) => path);
    expect(users).toEqual(["/src/admin/main.tsx"]);
  });
});

describe("admin/index.html head", () => {
  const doc = new DOMParser().parseFromString(adminIndexHtml, "text/html");

  test("Spanish, noindex and the admin title", () => {
    expect(doc.documentElement.getAttribute("lang")).toBe("es");
    expect(doc.head.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "noindex, nofollow",
    );
    expect(doc.head.querySelector("title")?.textContent).toBe("Administración · IdeologiApp");
  });

  test("same icons as the Voter page, same-origin only", () => {
    expect(doc.head.querySelector('link[rel="icon"]')?.getAttribute("href")).toBe(
      "/src/assets/ideologiapp-logo.svg",
    );
    expect(doc.head.querySelector('link[rel="apple-touch-icon"]')?.getAttribute("href")).toBe(
      "/src/assets/ideologiapp-touch-icon.png",
    );
    for (const link of doc.head.querySelectorAll("link[href]")) {
      expect(link.getAttribute("href")).toMatch(/^\/(?!\/)/);
    }
    expect(doc.querySelector('script[type="module"]')?.getAttribute("src")).toBe("/src/admin/main.tsx");
  });
});
