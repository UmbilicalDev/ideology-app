import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { RankedParty } from "@ideology-app/core";

import { textWithoutLogos } from "../../test/text";
import { ResultsRanking } from "./ResultsRanking";

const NBSP = " ";
const EXPLANATION =
  "Compartes menos de 5 afirmaciones con este partido, así que su afinidad se basa en pocos datos.";

function ranked(overrides: Partial<RankedParty> & Pick<RankedParty, "partyId" | "name">): RankedParty {
  return {
    shortName: `P${overrides.partyId}`,
    logoUrl: null,
    matchScore: 0.5,
    percent: 50,
    sharedStatementCount: 10,
    lowCoverage: false,
    ...overrides,
  };
}

function renderRanking(ranking: readonly RankedParty[]) {
  return render(
    <>
      <h2 id="results-title">Tus resultados</h2>
      <ResultsRanking ranking={ranking} />
    </>,
  );
}

function rows() {
  return within(screen.getByRole("list", { name: "Tus resultados" })).getAllByRole("listitem");
}

describe("ResultsRanking", () => {
  test("renders one row per Party in the given order, with name, short name, percent and count", () => {
    renderRanking([
      ranked({ partyId: 7, name: "Ñandú Unido", shortName: "ÑU", matchScore: 0.81, percent: 81, sharedStatementCount: 7 }),
      ranked({ partyId: 2, name: "Álava Común", shortName: "ÁC", matchScore: 0.555, percent: 56, sharedStatementCount: 1, lowCoverage: true }),
    ]);
    const items = rows();
    expect(items.map(textWithoutLogos)).toEqual([
      `Ñandú Unido ÑU 81${NBSP}%7 afirmaciones en común`,
      `Álava Común ÁC 56${NBSP}%1 afirmación en común Baja cobertura${EXPLANATION}`,
    ]);
    expect(items[0]!.querySelector(".ranking-bar__fill")?.getAttribute("style")).toBe("width: 81%;");
    expect(items[1]!.querySelector(".ranking-bar__fill")?.getAttribute("style")).toBe("width: 56%;");
    expect(screen.getByRole("list").getAttribute("aria-labelledby")).toBe("results-title");
  });

  test("a null score shows Sin afirmaciones en común, an empty track and the badge", () => {
    renderRanking([
      ranked({ partyId: 3, name: "Sin Datos", matchScore: null, percent: null, sharedStatementCount: 0, lowCoverage: true }),
    ]);
    const [row] = rows();
    expect(row!.querySelector(".ranking-row__percent")?.textContent).toBe("Sin afirmaciones en común");
    expect(textWithoutLogos(row!)).not.toContain("%");
    expect(row!.querySelector(".ranking-bar__fill")?.getAttribute("style")).toBe("width: 0%;");
    const chip = within(row!).getByRole("button", { name: "Baja cobertura" });
    expect(chip.className).toBe("coverage-badge");
    expect(within(row!).getByRole("tooltip", { hidden: true }).textContent).toBe(EXPLANATION);
  });

  test("the chip and its tooltip show only with low coverage", () => {
    renderRanking([
      ranked({ partyId: 1, name: "Uno", percent: 90 }),
      ranked({ partyId: 2, name: "Dos", percent: 10 }),
    ]);
    expect(screen.queryByText("Baja cobertura")).toBeNull();
    expect(screen.queryByText(EXPLANATION)).toBeNull();
    expect(screen.queryByText(/se basa en pocos datos/)).toBeNull();
  });

  test("one chip per low-coverage row, and no legend under the ranking", () => {
    renderRanking([
      ranked({ partyId: 1, name: "Uno", percent: 90 }),
      ranked({ partyId: 2, name: "Dos", percent: 40, sharedStatementCount: 4, lowCoverage: true }),
      ranked({ partyId: 3, name: "Tres", percent: 20, sharedStatementCount: 2, lowCoverage: true }),
    ]);
    expect(screen.getAllByRole("button", { name: "Baja cobertura" })).toHaveLength(2);
    expect(screen.getAllByRole("tooltip", { hidden: true })).toHaveLength(2);
    expect(within(rows()[0]!).queryByText("Baja cobertura")).toBeNull();
    expect(screen.getByRole("list").nextElementSibling).toBeNull();
  });

  test("the chip is described by its tooltip, which opens on hover, focus and tap and closes with Escape", () => {
    vi.useFakeTimers();
    try {
      renderRanking([ranked({ partyId: 2, name: "Dos", sharedStatementCount: 4, lowCoverage: true })]);
      const chip = screen.getByRole("button", { name: "Baja cobertura" });
      const tooltip = screen.getByRole("tooltip", { hidden: true });
      expect(chip.getAttribute("aria-describedby")).toBe(tooltip.id);
      expect(tooltip.hidden).toBe(true);
      expect(chip.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");

      fireEvent.mouseEnter(chip.parentElement!);
      expect(tooltip.hidden).toBe(false);
      fireEvent.mouseLeave(chip.parentElement!);
      expect(tooltip.hidden).toBe(false);
      act(() => vi.advanceTimersByTime(200));
      expect(tooltip.hidden).toBe(true);

      // Escape anywhere closes a tooltip opened by hover (WCAG 1.4.13).
      fireEvent.mouseEnter(chip.parentElement!);
      expect(tooltip.hidden).toBe(false);
      fireEvent.keyDown(document, { key: "Escape" });
      expect(tooltip.hidden).toBe(true);

      act(() => chip.focus());
      expect(tooltip.hidden).toBe(false);
      fireEvent.mouseEnter(chip.parentElement!);
      fireEvent.mouseLeave(chip.parentElement!);
      act(() => vi.advanceTimersByTime(200));
      expect(tooltip.hidden).toBe(false);
      fireEvent.keyDown(chip, { key: "Escape" });
      expect(tooltip.hidden).toBe(true);
      fireEvent.click(chip);
      expect(tooltip.hidden).toBe(false);
      fireEvent.blur(chip);
      expect(tooltip.hidden).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  test("every row gets the same tile: the logo when there is one, else the short-name placeholder", () => {
    const logo = "/api/v1/parties/1/logo?v=0000000000000001";
    renderRanking([
      ranked({ partyId: 1, name: "Primero", shortName: "PR", percent: 90, logoUrl: logo }),
      ranked({ partyId: 7, name: "Euskal Herria Bildu", shortName: "EH Bildu", percent: 60 }),
    ]);
    const [first, second] = rows().map((li) => li.querySelector(".ranking-row__head")!.firstElementChild!);
    expect(first!.className).toBe(second!.className);
    expect(first!.querySelector("img")?.getAttribute("src")).toBe(logo);
    expect(Array.from(second!.querySelectorAll("tspan"), (t) => t.textContent)).toEqual(["EH", "Bildu"]);
    // The names stay as text, and the tiles are hidden from assistive technology.
    expect(rows().map((li) => li.querySelector(".ranking-row__label")?.textContent)).toEqual([
      "Primero PR",
      "Euskal Herria Bildu EH Bildu",
    ]);
    expect(screen.queryAllByRole("img")).toHaveLength(0);
  });

  test("every row has the same markup: no per-Party colour, style or highlight; bars are decorative", () => {
    renderRanking([
      ranked({ partyId: 1, name: "Primero", shortName: "PR", percent: 90 }),
      ranked({ partyId: 2, name: "Segundo", shortName: "SE", percent: 60 }),
      ranked({ partyId: 3, name: "Tercero", shortName: "TE", percent: 30 }),
    ]);
    const items = rows();
    const structure = (li: HTMLElement) =>
      [li, ...li.querySelectorAll("*")].map((el) => `${el.tagName}.${el.className}`).join(" ");
    expect(new Set(items.map(structure)).size).toBe(1);
    for (const li of items) {
      expect(li.className).toBe("ranking-row");
      expect(li.getAttribute("style")).toBeNull();
      const styled = [...li.querySelectorAll("[style]")];
      expect(styled.map((el) => el.className)).toEqual(["ranking-bar__fill"]);
      expect(styled[0]!.getAttribute("style")).toMatch(/^width: \d+%;$/);
      expect(li.querySelector(".ranking-bar")?.getAttribute("aria-hidden")).toBe("true");
      const tiles = li.querySelectorAll(".party-logo");
      expect(tiles).toHaveLength(1);
      expect(li.querySelector(".ranking-row__head")?.firstElementChild).toBe(tiles[0]);
      expect(tiles[0]!.className).toBe("party-logo party-logo--ranking");
      expect(tiles[0]!.getAttribute("aria-hidden")).toBe("true");
      expect(li.querySelectorAll("img, svg")).toHaveLength(li.querySelectorAll(".party-logo svg").length);
    }
  });
});
