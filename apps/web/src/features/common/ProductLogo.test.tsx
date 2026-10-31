import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { ProductLogo } from "./ProductLogo";

describe("ProductLogo", () => {
  test("serves the dark variant by default and the light one under prefers-color-scheme: light", () => {
    const { container } = render(<ProductLogo className="sidebar__logo" size={36} />);
    const source = container.querySelector("picture > source")!;
    const img = container.querySelector("picture > img")!;
    expect(source.getAttribute("media")).toBe("(prefers-color-scheme: light)");
    expect(source.getAttribute("srcset")).toMatch(/ideologiapp-logo-light/);
    expect(img.getAttribute("src")).toMatch(/ideologiapp-logo\.svg|ideologiapp-logo-[^l]/);
    expect(img.getAttribute("src")).not.toMatch(/light/);
    expect(img.getAttribute("alt")).toBe("");
    expect(img.getAttribute("width")).toBe("36");
    expect(img.className).toBe("sidebar__logo");
  });
});
