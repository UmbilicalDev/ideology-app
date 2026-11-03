import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { FALLBACK_SLIDE_MS, HOW_IT_WORKS_SLIDES, HowItWorksCarousel } from "./HowItWorksCarousel";

const TITLES = [
  "Responde a las afirmaciones",
  "Revisa tus resultados",
  "Comprueba de dónde vienen los resultados",
];

function stubMatchMedia(matching: readonly string[]) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: matching.includes(query),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

function pages() {
  return Array.from(document.querySelectorAll<HTMLElement>(".how-slide"));
}

function currentIndex() {
  return pages().findIndex((page) => page.dataset.active === "true");
}

function currentVideo() {
  return pages()[currentIndex()]!.querySelector("video")!;
}

function carousel() {
  return screen.getByRole("region", { name: "Cómo funciona" });
}

describe("HowItWorksCarousel", () => {
  test("three pages with the requested text; only the current one is exposed", () => {
    render(<HowItWorksCarousel />);
    expect(carousel().getAttribute("aria-roledescription")).toBe("carrusel");
    expect(pages()).toHaveLength(3);
    expect(pages().map((page) => page.querySelector("h2")?.textContent)).toEqual(TITLES);
    expect(HOW_IT_WORKS_SLIDES.map((slide) => slide.points)).toEqual([
      [
        "Elige tu grado de acuerdo.",
        "Puedes saltarte las que quieras.",
        "Marca como importantes las que más te importan.",
      ],
      [
        "Comprueba en qué porcentaje coincides con cada partido.",
        "Comparte tu resultado con quien quieras.",
      ],
      [
        "Revisa qué dice exactamente cada partido sobre cada afirmación.",
        "Accede mediante enlace a las citas en los programas electorales.",
      ],
    ]);

    const group = screen.getByRole("group", { name: "1 de 3" });
    expect(group.getAttribute("aria-roledescription")).toBe("diapositiva");
    expect(within(group).getByText("Paso 1 de 3")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      TITLES[0],
    ]);
    pages()
      .slice(1)
      .forEach((page) => {
        expect(page.getAttribute("aria-hidden")).toBe("true");
        expect(page.hasAttribute("inert")).toBe(true);
      });
  });

  test("the recordings are decorative, muted and inline", () => {
    render(<HowItWorksCarousel />);
    for (const video of document.querySelectorAll("video")) {
      expect(video.getAttribute("aria-hidden")).toBe("true");
      expect(video.muted).toBe(true);
      expect(video.hasAttribute("playsinline")).toBe(true);
      expect(video.hasAttribute("controls")).toBe(false);
      expect(video.getAttribute("poster")).toBeTruthy();
    }
  });

  test("arrows move in an endless loop, both ways", () => {
    render(<HowItWorksCarousel />);
    const next = screen.getByRole("button", { name: "Página siguiente" });
    const previous = screen.getByRole("button", { name: "Página anterior" });

    fireEvent.click(previous);
    expect(currentIndex()).toBe(2);
    expect(pages()[2]!.dataset.direction).toBe("back");

    fireEvent.click(next);
    expect(currentIndex()).toBe(0);
    expect(pages()[0]!.dataset.direction).toBe("forward");
    fireEvent.click(next);
    fireEvent.click(next);
    fireEvent.click(next);
    expect(currentIndex()).toBe(0);
  });

  test("the three dots name their page and mark the current one", () => {
    render(<HowItWorksCarousel />);
    const dots = TITLES.map((title, index) =>
      screen.getByRole("button", { name: `Ir a la página ${index + 1}: ${title}` }),
    );
    expect(dots.map((dot) => dot.getAttribute("aria-current"))).toEqual(["true", null, null]);

    fireEvent.click(dots[2]!);
    expect(currentIndex()).toBe(2);
    expect(dots.map((dot) => dot.getAttribute("aria-current"))).toEqual([null, null, "true"]);
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      TITLES[2],
    ]);
  });

  test("plays the current recording and moves on when it ends", () => {
    render(<HowItWorksCarousel />);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(carousel().dataset.playing).toBe("true");
    expect(carousel().querySelector(".how-it-works__slides")?.getAttribute("aria-live")).toBe("off");

    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(1);
    fireEvent.ended(currentVideo());
    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(0);
  });

  test("hover and keyboard focus (not mouse focus) hold the page: the recording replays", () => {
    render(<HowItWorksCarousel />);
    fireEvent.pointerEnter(carousel(), { pointerType: "mouse" });
    expect(carousel().dataset.playing).toBe("false");
    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(0);

    fireEvent.pointerLeave(carousel(), { pointerType: "mouse" });
    // A mouse click focuses an arrow without :focus-visible: no hold.
    act(() => screen.getByRole("button", { name: "Página siguiente" }).focus());
    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(1);

    const matches = Element.prototype.matches;
    vi.spyOn(Element.prototype, "matches").mockImplementation(function (this: Element, selector) {
      return selector === ":focus-visible" ? true : matches.call(this, selector);
    });
    act(() => screen.getByRole("button", { name: "Pausar el carrusel" }).focus());
    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(1);
    expect(carousel().querySelector(".how-it-works__slides")?.getAttribute("aria-live")).toBe(
      "polite",
    );
  });

  test("the pause button stops the recording and the rotation, and resumes them", () => {
    render(<HowItWorksCarousel />);
    const pause = screen.getByRole("button", { name: "Pausar el carrusel" });
    fireEvent.click(pause);
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Reanudar el carrusel" })).toBe(pause);

    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(0);

    fireEvent.click(pause);
    expect(screen.getByRole("button", { name: "Pausar el carrusel" })).toBe(pause);
    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(1);
  });

  test("under reduced motion it starts paused and nothing plays", () => {
    stubMatchMedia(["(prefers-reduced-motion: reduce)"]);
    render(<HowItWorksCarousel />);
    expect(screen.getByRole("button", { name: "Reanudar el carrusel" })).toBeTruthy();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    fireEvent.ended(currentVideo());
    expect(currentIndex()).toBe(0);
  });

  test("the recordings follow the colour scheme", () => {
    render(<HowItWorksCarousel />);
    expect(currentVideo().getAttribute("src")).toBe(HOW_IT_WORKS_SLIDES[0]!.dark.video);
    stubMatchMedia(["(prefers-color-scheme: light)"]);
    render(<HowItWorksCarousel />);
    const light = document.querySelectorAll(".how-it-works")[1]!.querySelector("video")!;
    expect(light.getAttribute("src")).toBe(HOW_IT_WORKS_SLIDES[0]!.light.video);
    expect(light.getAttribute("poster")).toBe(HOW_IT_WORKS_SLIDES[0]!.light.poster);
  });

  test("a recording that cannot play still moves on after a delay", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValue(new Error("blocked"));
      render(<HowItWorksCarousel />);
      await act(async () => {});
      expect(currentIndex()).toBe(0);
      act(() => vi.advanceTimersByTime(FALLBACK_SLIDE_MS));
      expect(currentIndex()).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  test("a horizontal swipe changes page", () => {
    render(<HowItWorksCarousel />);
    const slides = carousel().querySelector(".how-it-works__slides")!;
    fireEvent.touchStart(slides, { touches: [{ clientX: 300 }] });
    fireEvent.touchEnd(slides, { changedTouches: [{ clientX: 200 }] });
    expect(currentIndex()).toBe(1);
    fireEvent.touchStart(slides, { touches: [{ clientX: 100 }] });
    fireEvent.touchEnd(slides, { changedTouches: [{ clientX: 220 }] });
    expect(currentIndex()).toBe(0);
    fireEvent.touchStart(slides, { touches: [{ clientX: 100 }] });
    fireEvent.touchEnd(slides, { changedTouches: [{ clientX: 120 }] });
    expect(currentIndex()).toBe(0);
  });
});
