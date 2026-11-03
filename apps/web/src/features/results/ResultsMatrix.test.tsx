import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import type { BreakdownPosition, BreakdownRow } from "@ideology-app/core";

import { textWithoutLogos } from "../../test/text";
import { coincidence, matchesFilter } from "./breakdown-view";
import { ResultsBreakdown } from "./ResultsBreakdown";

const UNO: BreakdownPosition = {
  partyId: 1,
  name: "Partido Uno",
  shortName: "P1",
  logoUrl: null,
  value: 2,
  evidence: { quote: "Bajaremos el IVA.", page: 3, href: "https://example.org/uno.pdf#page=3" },
};
const DOS: BreakdownPosition = {
  partyId: 2,
  name: "Partido Dos",
  shortName: "P2",
  logoUrl: null,
  value: -1,
  evidence: { quote: "Subiremos el IVA.", page: 7, href: null },
};
const TRES: BreakdownPosition = {
  partyId: 3,
  name: "Partido Tres",
  shortName: "P3",
  logoUrl: null,
  value: "no_stance",
  evidence: null,
};

function row(id: number, answer: BreakdownRow["answer"], important = false): BreakdownRow {
  return {
    statementId: id,
    position: id,
    text: `Afirmación de prueba ${id}.`,
    answer,
    important,
    positions: [UNO, DOS, TRES],
  };
}

const ROWS: BreakdownRow[] = [row(1, 1, true), row(2, -2), row(3, 0), row(4, "skip"), row(5, null)];

function stubWidth(wide: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: wide && query === "(min-width: 1024px)",
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
}

function chip(name: RegExp) {
  return within(screen.getByRole("group", { name: "Filtrar afirmaciones" })).getByRole("button", { name });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("breakdown view helpers", () => {
  test("coincidence follows the matching rule and is null without a rated Answer or a stance", () => {
    expect(coincidence(row(1, 2), UNO)).toBe(100);
    expect(coincidence(row(1, 1), UNO)).toBe(75);
    expect(coincidence(row(1, -2), UNO)).toBe(0);
    expect(coincidence(row(1, -2), DOS)).toBe(75);
    expect(coincidence(row(1, "skip"), UNO)).toBeNull();
    expect(coincidence(row(1, null), UNO)).toBeNull();
    expect(coincidence(row(1, 2), TRES)).toBeNull();
  });

  test("filters group the Muy grades with their side and Important needs the flag", () => {
    expect(ROWS.filter((r) => matchesFilter(r, "agree")).map((r) => r.statementId)).toEqual([1]);
    expect(ROWS.filter((r) => matchesFilter(r, "disagree")).map((r) => r.statementId)).toEqual([2]);
    expect(ROWS.filter((r) => matchesFilter(r, "neutral")).map((r) => r.statementId)).toEqual([3]);
    expect(ROWS.filter((r) => matchesFilter(r, "skipped")).map((r) => r.statementId)).toEqual([4]);
    expect(ROWS.filter((r) => matchesFilter(r, "important")).map((r) => r.statementId)).toEqual([1]);
    expect(ROWS.filter((r) => matchesFilter(r, "all"))).toHaveLength(5);
  });
});

describe("ResultsBreakdown filters (cards, below 1024px)", () => {
  beforeEach(() => stubWidth(false));

  test("chips show their counts, one is pressed, and a filter narrows the cards", () => {
    render(<ResultsBreakdown rows={ROWS} />);
    expect(screen.queryByRole("table")).toBeNull();
    expect(chip(/^Todas/).getAttribute("aria-pressed")).toBe("true");
    expect(chip(/^Todas/).textContent).toBe("Todas5");
    expect(chip(/^Saltadas/).textContent).toBe("Saltadas1");

    fireEvent.click(chip(/^En desacuerdo/));
    expect(chip(/^En desacuerdo/).getAttribute("aria-pressed")).toBe("true");
    expect(chip(/^Todas/).getAttribute("aria-pressed")).toBe("false");
    const cards = within(screen.getByRole("list", { name: "Comprueba de dónde salen tus coincidencias" })).getAllByRole("heading", {
      level: 4,
    });
    expect(cards.map((h) => h.textContent)).toEqual(["Afirmación de prueba 2."]);
    expect(screen.getByRole("status").textContent).toBe("1 de 5 afirmaciones");
  });

  test("a filter with no rows says so", () => {
    render(<ResultsBreakdown rows={[row(1, 1)]} />);
    fireEvent.click(chip(/^Saltadas/));
    expect(screen.getByText("Ninguna afirmación coincide con este filtro.")).toBeTruthy();
  });
});

describe("ResultsMatrix (1024px and up)", () => {
  beforeEach(() => stubWidth(true));

  test("one identical column per Party in the given order and a labelled cell per Position", () => {
    render(<ResultsBreakdown rows={ROWS} />);
    const table = screen.getByRole("table");
    const heads = within(table).getAllByRole("columnheader").map((th) => textWithoutLogos(th));
    expect(heads).toEqual(["Afirmación", "Tú", "P1Partido Uno", "P2Partido Dos", "P3Partido Tres"]);
    const first = within(table).getAllByRole("row")[1]!;
    const cells = within(first).getAllByRole("button").slice(1);
    // A stance is drawn as its scale icon (decorative); no stance is a dash.
    const shown = (c: HTMLElement) => (c.querySelector("svg[aria-hidden='true']") === null ? c.textContent : "icon");
    expect(cells.map((c) => [shown(c), c.getAttribute("data-match"), c.getAttribute("aria-label")])).toEqual([
      ["icon", "75", "Partido Uno: Muy de acuerdo, coincidencia 75 %. Ver la cita"],
      ["icon", "50", "Partido Dos: En desacuerdo, coincidencia 50 %. Ver la cita"],
      ["—", "none", "Partido Tres: Sin posición en el programa"],
    ]);
    // Same markup and classes for every Party: no per-Party styling.
    expect(new Set(cells.map((c) => c.className))).toEqual(new Set(["match-cell"]));
    expect(cells.every((c) => c.getAttribute("style") === null)).toBe(true);
    expect(within(first).getByText("De acuerdo").className).toBe("visually-hidden");
  });

  test("a skipped Statement has no coincidence in any cell", () => {
    render(<ResultsBreakdown rows={[row(4, "skip")]} />);
    const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("button").slice(1);
    expect(cells.map((c) => c.getAttribute("data-match"))).toEqual(["none", "none", "none"]);
  });

  test("a cell opens its Evidence in the inspector; Escape closes it and focus returns", () => {
    render(<ResultsBreakdown rows={ROWS} />);
    const cell = screen.getAllByRole("button", { name: /^Partido Dos: En desacuerdo/ })[0]!;
    fireEvent.click(cell);
    const dialog = screen.getByRole("dialog", { name: "Afirmación de prueba 1." });
    expect(within(dialog).getByText("Subiremos el IVA.").tagName).toBe("BLOCKQUOTE");
    expect(dialog.querySelector(".inspector-position__match")?.textContent).toBe(
      " · coincidencia contigo 50\u00a0%",
    );
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(1);
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cerrar" }));

    fireEvent.click(within(dialog).getByRole("button", { name: "Ver todos los partidos en esta afirmación" }));
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(3);
    expect(document.activeElement).toBe(within(dialog).getByRole("heading", { level: 2 }));

    act(() => {
      fireEvent(dialog, new Event("cancel", { cancelable: true }));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(cell);
  });

  test("a Statement opens every Party's Position", () => {
    render(<ResultsBreakdown rows={ROWS} answerOwner="link" />);
    expect(screen.getAllByRole("columnheader")[1]!.textContent).toBe("Enlace");
    fireEvent.click(screen.getByRole("button", { name: /Afirmación de prueba 3\./ }));
    const dialog = screen.getByRole("dialog", { name: "Afirmación de prueba 3." });
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(3);
    expect(within(dialog).getByText("Respuesta del enlace:", { exact: false })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: /Ver todos/ })).toBeNull();
  });

  test("the answer cell opens the Statement too, and focus returns to the Statement button", () => {
    render(<ResultsBreakdown rows={ROWS} />);
    const tableRow = screen.getAllByRole("row")[1]!;
    const answerCell = tableRow.querySelector<HTMLElement>(".matrix__answer")!;
    // Not a second tab stop: the Statement button stays the keyboard way in.
    expect(answerCell.querySelector("button, [tabindex]")).toBeNull();
    fireEvent.click(answerCell.querySelector(".answer-chip")!);
    const dialog = screen.getByRole("dialog", { name: "Afirmación de prueba 1." });
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(3);
    act(() => {
      fireEvent(dialog, new Event("cancel", { cancelable: true }));
    });
    expect(document.activeElement).toBe(tableRow.querySelector(".matrix__statement-button"));
  });
});
