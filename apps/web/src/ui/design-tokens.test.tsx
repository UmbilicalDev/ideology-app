// Guards the CONSTRAINTS.md "Web Client Styling" rules: every colour, font
// and shadow comes from tokens.css, which mirrors DESIGN.md (light and dark),
// and no stylesheet reaches another origin.
import { describe, expect, test } from "vitest";

const sheets = import.meta.glob<string>("./*.css", {
  query: "?raw",
  import: "default",
  eager: true,
});

const TOKENS = "./tokens.css";

function withoutComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function declarations(css: string, property: string): string[] {
  const pattern = new RegExp(`(?:^|[;{\\s])${property}\\s*:\\s*([^;}]+)`, "g");
  return Array.from(withoutComments(css).matchAll(pattern), (match) => match[1]!.trim());
}

const componentSheets = Object.entries(sheets).filter(([path]) => path !== TOKENS);

describe("design tokens", () => {
  test("the stylesheets are found", () => {
    expect(Object.keys(sheets).sort()).toEqual(["./components.css", "./global.css", "./tokens.css"]);
  });

  test.each(componentSheets)("%s has no hard-coded colour", (_path, css) => {
    const body = withoutComments(css);
    expect(body.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
    expect(body.match(/\b(?:rgba?|hsla?)\(/g)).toBeNull();
  });

  test.each(componentSheets)("%s takes fonts and shadows only from tokens", (_path, css) => {
    const values = [
      ...declarations(css, "font-family"),
      ...declarations(css, "font"),
      ...declarations(css, "box-shadow"),
    ];
    const literal = values.filter((value) => !value.includes("var(") && value !== "inherit");
    expect(literal).toEqual([]);
  });

  test("tokens.css has a dark theme and Public Sans, and no old typefaces", () => {
    const tokens = sheets[TOKENS]!;
    expect(tokens).toContain("prefers-color-scheme: dark");
    expect(tokens).toContain("Public Sans");
    expect(tokens).not.toMatch(/Georgia|Inter\b/);
  });

  test("the party-logo tile colours are declared once and fixed in both themes", () => {
    const tokens = withoutComments(sheets[TOKENS]!);
    for (const [name, value] of [
      ["--color-party-logo-tile", "#ffffff"],
      ["--color-on-party-logo-tile", "#3f484d"],
    ] as const) {
      expect(declarations(tokens, name)).toEqual([value]);
    }
    const darkStart = tokens.indexOf("@media (prefers-color-scheme: dark)");
    expect(darkStart).toBeGreaterThan(-1);
    const darkEnd = tokens.indexOf("@media", darkStart + 1);
    const dark = tokens.slice(darkStart, darkEnd === -1 ? undefined : darkEnd);
    expect(dark).not.toContain("--color-party-logo-tile");
    expect(dark).not.toContain("--color-on-party-logo-tile");
  });

  test.each(Object.entries(sheets))("%s loads nothing from another origin", (_path, css) => {
    expect(css).not.toMatch(/url\(\s*["']?(?:https?:)?\/\//i);
    expect(css).not.toMatch(/@import\s+(?:url\()?\s*["']?(?:https?:)?\/\//i);
  });
});
