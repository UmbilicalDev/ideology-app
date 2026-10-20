import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { RankedParty } from "@ideology-app/core";

import { ResultsRanking } from "./ResultsRanking";

const NBSP = " ";
const LEGEND =
  "Baja cobertura: compartes menos de 5 afirmaciones con ese partido, así que su afinidad se " +
  "basa en pocos datos.";

function ranked(overrides: Partial<RankedParty> & Pick<RankedParty, "partyId" | "name">): RankedParty {
  return {
    shortName: `P${overrides.partyId}`,
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
    expect(items.map((li) => li.textContent)).toEqual([
      `Ñandú Unido ÑU 81${NBSP}%7 afirmaciones en común`,
      `Álava Común ÁC 56${NBSP}%1 afirmación en común Baja cobertura`,
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
    expect(row!.textContent).not.toContain("%");
    expect(row!.querySelector(".ranking-bar__fill")?.getAttribute("style")).toBe("width: 0%;");
    expect(within(row!).getByText("Baja cobertura").className).toBe("coverage-badge");
    expect(screen.getByText(LEGEND).className).toBe("ranking-legend");
  });

  test("the badge and the legend show only with low coverage", () => {
    renderRanking([
      ranked({ partyId: 1, name: "Uno", percent: 90 }),
      ranked({ partyId: 2, name: "Dos", percent: 10 }),
    ]);
    expect(screen.queryByText("Baja cobertura")).toBeNull();
    expect(screen.queryByText(LEGEND)).toBeNull();
  });

  test("the legend shows once, with one badge per low-coverage row", () => {
    renderRanking([
      ranked({ partyId: 1, name: "Uno", percent: 90 }),
      ranked({ partyId: 2, name: "Dos", percent: 40, sharedStatementCount: 4, lowCoverage: true }),
      ranked({ partyId: 3, name: "Tres", percent: 20, sharedStatementCount: 2, lowCoverage: true }),
    ]);
    expect(screen.getAllByText("Baja cobertura")).toHaveLength(2);
    expect(screen.getAllByText(LEGEND)).toHaveLength(1);
    expect(within(rows()[0]!).queryByText("Baja cobertura")).toBeNull();
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
      expect(li.querySelector("img, svg")).toBeNull();
    }
  });
});
