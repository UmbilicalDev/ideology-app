// donate-buymeacoffee: the profile URL is configuration, never code. In the
// shipped Voter and core sources only the core pattern names Buy Me a Coffee's
// host, and nothing builds a donation href or adds tracking parameters.
import { describe, expect, test } from "vitest";

import indexHtml from "../../../index.html?raw";

// The same glob as `features/legal/browser-storage.test.tsx`.
const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "../../../../../packages/core/src/**/*.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const isTest = (path: string) => path.endsWith(".test.tsx") || path.startsWith("/src/test/");
const shipped = Object.entries(sources).filter(([path]) => !isTest(path));

describe("donation sources", () => {
  test("the scan sees the donation sources", () => {
    const paths = shipped.map(([path]) => path);
    expect(paths).toContain("/src/features/donate/DonationLink.tsx");
    expect(paths.some((p) => p.endsWith("packages/core/src/domain/donation.ts"))).toBe(true);
  });

  // The host (`buymeacoffee.com`, or `buymeacoffee\.com` in the pattern); the
  // feature id `donate-buymeacoffee` in comments does not count.
  test("the buymeacoffee host appears only in packages/core/src/domain/donation.ts", () => {
    const host = /buymeacoffee\\?\.com/i;
    const naming = shipped.filter(([, source]) => host.test(source)).map(([p]) => p);
    expect(naming).toHaveLength(1);
    expect(naming[0]).toMatch(/packages\/core\/src\/domain\/donation\.ts$/);
    expect(indexHtml).not.toMatch(host);
  });

  test.each(shipped)("%s sets no utm_ parameter", (_path, source) => {
    expect(source).not.toContain("utm_");
  });

  test("the link's href is the URL itself, never built by concatenation", () => {
    const link = shipped.find(([p]) => p === "/src/features/donate/DonationLink.tsx")![1];
    expect(link).toContain("href={url}");
    expect(link).not.toMatch(/href=\{`|href=\{url\s*\+|href=\{[^}]*\+\s*url/);
    for (const [, source] of shipped) {
      expect(source).not.toMatch(/donation[A-Za-z]*\s*\+\s*["'`?#]/i);
      expect(source).not.toMatch(/\$\{donation[A-Za-z]*\}/i);
    }
  });
});
