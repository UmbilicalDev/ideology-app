// Guards the document head (DESIGN.md "Existing Design Assets"): the tab title is the
// product name and the tab icon is the product logo, served by the app itself.
import { describe, expect, test } from "vitest";
import indexHtml from "../../index.html?raw";

const head = new DOMParser().parseFromString(indexHtml, "text/html").head;

describe("index.html head", () => {
  test("the tab title is the product name", () => {
    expect(head.querySelector("title")?.textContent).toBe("IdeologiApp");
  });

  test("the tab icon is the product logo as SVG", () => {
    const icons = head.querySelectorAll('link[rel="icon"]');
    expect(icons).toHaveLength(1);
    expect(icons[0]!.getAttribute("type")).toBe("image/svg+xml");
    expect(icons[0]!.getAttribute("href")).toBe("/src/assets/ideologiapp-logo.svg");
  });

  test("the home-screen icon is the opaque PNG of the logo", () => {
    const touch = head.querySelectorAll('link[rel="apple-touch-icon"]');
    expect(touch).toHaveLength(1);
    expect(touch[0]!.getAttribute("href")).toBe("/src/assets/ideologiapp-touch-icon.png");
  });

  test("every head link is same-origin", () => {
    for (const link of head.querySelectorAll("link[href]")) {
      expect(link.getAttribute("href")).toMatch(/^\/(?!\/)/);
    }
  });
});
