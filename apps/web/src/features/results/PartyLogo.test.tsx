import { fireEvent, render } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { partyLogoUrl, recordImageRequests } from "../../test/fetch-mocks";
import { PartyLogo, placeholderLayout } from "./PartyLogo";
import { forgetPreloadedPartyLogos, preloadPartyLogos } from "./party-logo-preload";

function texts(shortName: string): string[] {
  return placeholderLayout(shortName).lines.map((line) => line.text);
}

describe("placeholderLayout", () => {
  test("a short name stays on one line in the minimum 28x28 box, centred", () => {
    const layout = placeholderLayout("PP");
    expect(texts("PP")).toEqual(["PP"]);
    expect([layout.width, layout.height, layout.x]).toEqual([28, 28, 14]);
    // One 12-unit line centred vertically: baseline = 8 + 6 + 3.5.
    expect(layout.lines[0]!.y).toBeCloseTo(17.5);
  });

  test("a long name without space or hyphen stays on one line and widens the box", () => {
    const layout = placeholderLayout("SUMAR");
    expect(texts("SUMAR")).toEqual(["SUMAR"]);
    expect(layout.width).toBeCloseTo(5 * 7.2 + 4);
    expect(layout.height).toBe(28);
    expect(layout.x).toBeCloseTo(layout.width / 2);
  });

  test("a space splits once and is dropped", () => {
    expect(texts("EH Bildu")).toEqual(["EH", "Bildu"]);
    const layout = placeholderLayout("EH Bildu");
    expect(layout.width).toBeCloseTo(5 * 7.2 + 4);
    expect(layout.height).toBe(28);
    expect(layout.lines.map((l) => l.y)).toEqual([11.5, 23.5]);
  });

  test("a hyphen splits once and stays at the end of the first line", () => {
    expect(texts("EAJ-PNV")).toEqual(["EAJ-", "PNV"]);
    expect(placeholderLayout("EAJ-PNV").width).toBeCloseTo(4 * 7.2 + 4);
  });

  test("a name of 4 characters or fewer is never split, even with a space", () => {
    expect(texts("A B")).toEqual(["A B"]);
    expect(texts("P-1")).toEqual(["P-1"]);
  });

  test("only the first separator splits, so there are at most 2 lines", () => {
    expect(texts("Más País-Equo Verdes")).toEqual(["Más", "País-Equo Verdes"]);
  });

  test("a 50-character name gets a box wide enough for its longest line", () => {
    const name = "X".repeat(50);
    const layout = placeholderLayout(name);
    expect(texts(name)).toEqual([name]);
    expect(layout.width).toBeCloseTo(50 * 7.2 + 4);
    expect(layout.height).toBe(28);
  });
});

describe("PartyLogo", () => {
  test("a logo renders a decorative img with the exact URL inside the tile", () => {
    const url = partyLogoUrl(3);
    const { container } = render(<PartyLogo logoUrl={url} shortName="PP" size="ranking" />);
    const tile = container.firstElementChild!;
    expect(tile.className).toBe("party-logo party-logo--ranking");
    expect(tile.getAttribute("aria-hidden")).toBe("true");
    const img = tile.querySelector("img")!;
    expect(img.getAttribute("src")).toBe(url);
    expect(img.getAttribute("alt")).toBe("");
    expect(img.className).toBe("party-logo__img");
    expect(img.getAttribute("loading")).toBeNull();
    expect(img.getAttribute("width")).toBe("256");
    expect(img.getAttribute("height")).toBe("256");
    expect(tile.querySelector("svg")).toBeNull();
  });

  test("a null logo renders the short-name placeholder", () => {
    const { container } = render(<PartyLogo logoUrl={null} shortName="EH Bildu" size="breakdown" />);
    const tile = container.firstElementChild!;
    expect(tile.className).toBe("party-logo party-logo--breakdown");
    expect(tile.querySelector("img")).toBeNull();
    const svg = tile.querySelector("svg")!;
    expect(svg.getAttribute("class")).toBe("party-logo__placeholder");
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("focusable")).toBe("false");
    expect(svg.getAttribute("preserveAspectRatio")).toBe("xMidYMid meet");
    expect(svg.getAttribute("viewBox")).toBe(`0 0 ${5 * 7.2 + 4} 28`);
    const text = svg.querySelector("text")!;
    expect(text.getAttribute("class")).toBe("party-logo__text");
    expect(text.getAttribute("text-anchor")).toBe("middle");
    expect(Array.from(text.querySelectorAll("tspan"), (t) => t.textContent)).toEqual(["EH", "Bildu"]);
  });

  test("a logo that fails to load becomes the placeholder inside the same tile node", () => {
    const { container } = render(<PartyLogo logoUrl={partyLogoUrl(4)} shortName="SUMAR" size="ranking" />);
    const tile = container.firstElementChild!;
    fireEvent.error(tile.querySelector("img")!);
    expect(container.firstElementChild).toBe(tile);
    expect(tile.className).toBe("party-logo party-logo--ranking");
    expect(tile.querySelector("img")).toBeNull();
    expect(tile.querySelector("tspan")?.textContent).toBe("SUMAR");
  });

  test("a new logoUrl after a failure shows the new logo again", () => {
    const { container, rerender } = render(
      <PartyLogo logoUrl={partyLogoUrl(4)} shortName="SUMAR" size="ranking" />,
    );
    fireEvent.error(container.querySelector("img")!);
    expect(container.querySelector("img")).toBeNull();
    rerender(<PartyLogo logoUrl={partyLogoUrl(5)} shortName="SUMAR" size="ranking" />);
    expect(container.querySelector("img")?.getAttribute("src")).toBe(partyLogoUrl(5));
  });

  test("the tile class is identical for a logo, a placeholder and a failed logo", () => {
    const logo = render(<PartyLogo logoUrl={partyLogoUrl(1)} shortName="PP" size="breakdown" />);
    const none = render(<PartyLogo logoUrl={null} shortName="PP" size="breakdown" />);
    const failed = render(<PartyLogo logoUrl={partyLogoUrl(2)} shortName="PP" size="breakdown" />);
    fireEvent.error(failed.container.querySelector("img")!);
    const classes = [logo, none, failed].map((r) => r.container.firstElementChild!.className);
    expect(new Set(classes)).toEqual(new Set(["party-logo party-logo--breakdown"]));
  });
});

describe("preloadPartyLogos", () => {
  test("requests every non-null logo once, in input order, through Image", () => {
    const { srcs } = recordImageRequests();
    preloadPartyLogos([
      { logoUrl: partyLogoUrl(1) },
      { logoUrl: null },
      { logoUrl: partyLogoUrl(3) },
      { logoUrl: partyLogoUrl(2) },
    ]);
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(3), partyLogoUrl(2)]);
  });

  test("a repeated URL is requested only once, also across calls", () => {
    const { srcs } = recordImageRequests();
    preloadPartyLogos([{ logoUrl: partyLogoUrl(1) }, { logoUrl: partyLogoUrl(1) }]);
    preloadPartyLogos([{ logoUrl: partyLogoUrl(2) }, { logoUrl: partyLogoUrl(1) }]);
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(2)]);
    forgetPreloadedPartyLogos();
    preloadPartyLogos([{ logoUrl: partyLogoUrl(1) }]);
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(2), partyLogoUrl(1)]);
  });

  test("no logos means no request", () => {
    const { srcs } = recordImageRequests();
    preloadPartyLogos([{ logoUrl: null }, { logoUrl: null }]);
    preloadPartyLogos([]);
    expect(srcs).toEqual([]);
  });
});
