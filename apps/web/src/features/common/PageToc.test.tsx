import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { PageToc, type TocEntry } from "./PageToc";

const ENTRIES: readonly TocEntry[] = [
  { id: "one", label: "Uno" },
  { id: "two", label: "Dos" },
  { id: "three", label: "Tres" },
];

// Heading tops relative to the viewport, as the page would lay them out.
let tops: Record<string, number> = {};
let scrollHeight = 3000;

function renderPage() {
  return render(
    <>
      <PageToc entries={ENTRIES} />
      {ENTRIES.map((entry) => (
        <h2 key={entry.id} id={entry.id}>
          {entry.label}
        </h2>
      ))}
    </>,
  );
}

function current() {
  return screen
    .getAllByRole("link")
    .filter((link) => link.getAttribute("aria-current") === "location")
    .map((link) => link.textContent);
}

function scrollTo(y: number, nextTops: Record<string, number>) {
  tops = nextTops;
  act(() => {
    Object.defineProperty(window, "scrollY", { configurable: true, value: y });
    fireEvent.scroll(window);
  });
}

beforeEach(() => {
  tops = { one: 400, two: 1400, three: 2400 };
  scrollHeight = 3000;
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 1000 });
  Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
  Object.defineProperty(document.documentElement, "scrollHeight", {
    configurable: true,
    get: () => scrollHeight,
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    const top = tops[this.id] ?? 0;
    return { top, bottom: top + 40, left: 0, right: 0, width: 0, height: 40, x: 0, y: top } as DOMRect;
  });
  // Run the frame at once. The id 0 means "no frame pending", like after a real
  // frame has run, so the next scroll schedules again.
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    callback(0);
    return 0;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PageToc", () => {
  test("marks the first entry before the first heading reaches the active line", () => {
    renderPage();
    expect(current()).toEqual(["Uno"]);
    expect(screen.getByRole("navigation", { name: "En esta página" })).toBeTruthy();
  });

  test("follows the scroll: the last heading at or above 30 % of the viewport is current", () => {
    renderPage();
    scrollTo(1200, { one: -800, two: 200, three: 1200 });
    expect(current()).toEqual(["Dos"]);
    scrollTo(800, { one: -400, two: 600, three: 1600 });
    expect(current()).toEqual(["Uno"]);
    scrollTo(1000, { one: -600, two: 300, three: 1400 });
    expect(current()).toEqual(["Dos"]);
  });

  test("marks the last entry at the end of the page even if its heading is low", () => {
    renderPage();
    scrollTo(2000, { one: -1600, two: -600, three: 500 });
    expect(current()).toEqual(["Tres"]);
  });

  test("a clicked entry is marked at once and kept while its heading is on screen", () => {
    renderPage();
    fireEvent.click(screen.getByRole("link", { name: "Dos" }));
    expect(current()).toEqual(["Dos"]);
    // The jump lands at the end of the page: the bottom rule would say "Tres".
    scrollTo(2000, { one: -1600, two: 120, three: 500 });
    expect(current()).toEqual(["Dos"]);
    // Scrolling by hand gives control back to the scroll position.
    act(() => {
      fireEvent.wheel(window);
    });
    scrollTo(2000, { one: -1600, two: 120, three: 500 });
    expect(current()).toEqual(["Tres"]);
  });

  test("links still point at their headings", () => {
    renderPage();
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "#one",
      "#two",
      "#three",
    ]);
  });
});
