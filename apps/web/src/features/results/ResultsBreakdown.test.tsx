import { cleanup, render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { BreakdownPosition, BreakdownRow } from "@ideology-app/core";

import { textWithoutLogos } from "../../test/text";
import { ResultsBreakdown } from "./ResultsBreakdown";

const INTRO =
  "Haz click en una afirmación o posición para ver las citas coincidentes extraídas de los " +
  "programas electorales.";
const LINK_TITLE = "Comprueba de dónde salen las coincidencias del enlace";
const NO_STANCE_SENTENCE =
  "El programa de este partido no trata esta afirmación, así que no cuenta para su afinidad.";

const UNO_URL: BreakdownPosition = {
  partyId: 1,
  name: "Partido Uno",
  shortName: "P1",
  logoUrl: null,
  value: 2,
  evidence: { quote: "Bajaremos el IVA.", page: 3, href: "https://example.org/uno.pdf#page=3" },
};
const DOS_UPLOAD: BreakdownPosition = {
  partyId: 2,
  name: "Partido Dos",
  shortName: "P2",
  logoUrl: null,
  value: -1,
  evidence: { quote: "<b>x</b>", page: 7, href: null },
};
const TRES_NONE: BreakdownPosition = {
  partyId: 3,
  name: "Partido Tres",
  shortName: "P3",
  logoUrl: null,
  value: "no_stance",
  evidence: null,
};

const ROWS: BreakdownRow[] = [
  {
    statementId: 101,
    position: 1,
    text: "Primera afirmación.",
    answer: 1,
    important: true,
    positions: [UNO_URL, DOS_UPLOAD, TRES_NONE],
  },
  {
    statementId: 102,
    position: 2,
    text: "Segunda afirmación.",
    answer: "skip",
    important: false,
    positions: [UNO_URL, DOS_UPLOAD, TRES_NONE],
  },
  {
    statementId: 103,
    position: 3,
    text: "Tercera afirmación.",
    answer: null,
    important: false,
    positions: [UNO_URL, DOS_UPLOAD, TRES_NONE],
  },
];

function renderBreakdown(rows: readonly BreakdownRow[] = ROWS) {
  return render(<ResultsBreakdown rows={rows} />);
}

function rows(name = "Comprueba de dónde salen tus coincidencias") {
  return Array.from(screen.getByRole("list", { name }).children) as HTMLElement[];
}

function items(row: HTMLElement) {
  return Array.from(row.querySelectorAll<HTMLDetailsElement>("details"));
}

describe("ResultsBreakdown", () => {
  test("heading, intro, numbered rows with h4 Statement text", () => {
    renderBreakdown();
    const h3 = screen.getByRole("heading", { level: 3 });
    expect(h3.textContent).toBe("Comprueba de dónde salen tus coincidencias");
    expect(h3.id).toBe("breakdown-title");
    expect(screen.getByText(INTRO)).toBeTruthy();
    expect(rows()).toHaveLength(3);
    expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual([
      "Primera afirmación.",
      "Segunda afirmación.",
      "Tercera afirmación.",
    ]);
    expect(rows().map((r) => r.querySelector(".breakdown-row__number")?.textContent)).toEqual([
      "Afirmación 1",
      "Afirmación 2",
      "Afirmación 3",
    ]);
  });

  test("answer labels and the Important mark only when important", () => {
    renderBreakdown();
    const answers = rows().map((r) => r.querySelector(".breakdown-row__answer")!);
    expect(answers.map((a) => a.textContent)).toEqual([
      "Tu respuesta: De acuerdo Importante (cuenta el doble)",
      "Tu respuesta: Saltada (no cuenta para la afinidad)",
      "Tu respuesta: Sin responder",
    ]);
    expect(answers[0]!.querySelector("strong")?.textContent).toBe("De acuerdo");
    expect(screen.getAllByText("Importante (cuenta el doble)")).toHaveLength(1);
    expect(screen.getByText("Importante (cuenta el doble)").className).toBe("important-mark");
    // Leading icons: the scale icon, step-over when skipped, none when unanswered;
    // the Important mark carries the star. All decorative.
    expect(answers.map((a) => a.querySelector("strong svg")?.getAttribute("class") ?? null)).toEqual([
      "icon icon--wide value-icon",
      "icon value-icon",
      null,
    ]);
    const star = screen.getByText("Importante (cuenta el doble)").querySelector("svg");
    expect(star?.getAttribute("class")).toBe("icon important-mark__star");
    expect(star?.getAttribute("aria-hidden")).toBe("true");
  });

  test("one closed details per row and Party, with scale labels and no stance in the summary", () => {
    renderBreakdown();
    for (const row of rows()) {
      const details = items(row);
      expect(details).toHaveLength(3);
      expect(details.every((d) => !d.open)).toBe(true);
      expect(details.map((d) => textWithoutLogos(d.querySelector("summary")!))).toEqual([
        "Partido Uno P1 Muy de acuerdo",
        "Partido Dos P2 En desacuerdo",
        "Partido Tres P3 Sin posición en el programa",
      ]);
    }
  });

  test("URL Evidence: quote in a blockquote and a new-tab link to the page", () => {
    renderBreakdown();
    const uno = items(rows()[0]!)[0]!;
    const quote = uno.querySelector("blockquote")!;
    expect(quote.className).toBe("evidence__quote");
    expect(quote.textContent).toBe("Bajaremos el IVA.");
    const link = within(uno).getByRole("link", {
      name: "Ver en el programa, página 3 (se abre en una pestaña nueva)",
      hidden: true,
    });
    expect(link.getAttribute("href")).toBe("https://example.org/uno.pdf#page=3");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.className).toBe("text-link");
  });

  test("uploaded Evidence: quote rendered literally, the page sentence and no link", () => {
    renderBreakdown();
    const dos = items(rows()[0]!)[1]!;
    const quote = dos.querySelector("blockquote.evidence__quote")!;
    expect(quote.textContent).toBe("<b>x</b>");
    expect(quote.querySelector("b")).toBeNull();
    expect(dos.querySelector(".evidence__page")?.textContent).toBe(
      "Página 7 del programa electoral. Este documento no tiene un enlace público.",
    );
    expect(dos.querySelector("a")).toBeNull();
  });

  test("no stance: the sentence, no quote and no link", () => {
    renderBreakdown();
    const tres = items(rows()[0]!)[2]!;
    expect(tres.querySelector(".evidence__none")?.textContent).toBe(NO_STANCE_SENTENCE);
    expect(tres.querySelector("blockquote")).toBeNull();
    expect(tres.querySelector("a")).toBeNull();
  });

  test("every Party item has identical class names and nothing is styled inline", () => {
    const { container } = renderBreakdown();
    const signature = (d: HTMLDetailsElement) =>
      [d, ...Array.from(d.querySelectorAll("summary, summary > span, .position__label > span"))].map(
        (el) => el.className,
      );
    const all = Array.from(container.querySelectorAll<HTMLDetailsElement>("details"));
    expect(all).toHaveLength(9);
    for (const d of all) {
      expect(signature(d)).toEqual(signature(all[0]!));
      expect((d.parentElement as HTMLElement).getAttribute("class")).toBeNull();
    }
    expect(container.querySelector("[style]")).toBeNull();
    // The only image content is the decorative party-logo tile, first in
    // every summary, identical for every Party.
    const tiles = Array.from(container.querySelectorAll(".party-logo"));
    expect(tiles).toHaveLength(9);
    for (const d of all) {
      const tile = d.querySelector("summary")!.firstElementChild!;
      expect(tile.className).toBe("party-logo party-logo--breakdown");
      expect(tile.getAttribute("aria-hidden")).toBe("true");
      // The tile is followed by one text box holding name, short name and stance.
      const summaryChildren = Array.from(d.querySelector("summary")!.children, (el) => el.className);
      expect(summaryChildren).toEqual(["party-logo party-logo--breakdown", "position__label"]);
      expect(
        Array.from(d.querySelector(".position__label")!.children, (el) => el.className),
      ).toEqual(["position__name", "position__short", "position__value"]);
    }
    // Besides the logos, only the Answer line (scale icon, Important star)
    // and each stance's scale icon carry graphics, the same for every Party.
    expect(container.querySelectorAll("img, svg")).toHaveLength(
      container.querySelectorAll(
        ".party-logo img, .party-logo svg, .breakdown-row__answer svg, .position__value svg",
      ).length,
    );
  });

  test("an empty list renders the section with no rows", () => {
    renderBreakdown([]);
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe("Comprueba de dónde salen tus coincidencias");
    expect(screen.getByRole("list", { name: "Comprueba de dónde salen tus coincidencias" }).children).toHaveLength(0);
  });

  test('answerOwner="link" names the link\'s Answer; markup otherwise identical', () => {
    const voter = renderBreakdown().container.innerHTML;
    cleanup();
    const { container } = render(<ResultsBreakdown rows={ROWS} answerOwner="link" />);
    expect(screen.getByRole("heading", { level: 3, name: LINK_TITLE })).toBeTruthy();
    expect(screen.getByText(INTRO)).toBeTruthy();
    expect(rows(LINK_TITLE).map((r) => r.querySelector(".breakdown-row__answer")?.textContent)).toEqual([
      "Respuesta del enlace: De acuerdo Importante (cuenta el doble)",
      "Respuesta del enlace: Saltada (no cuenta para la afinidad)",
      "Respuesta del enlace: Sin responder",
    ]);
    expect(container.textContent).not.toContain("Tu respuesta");
    const normalise = (html: string) =>
      html
        .replaceAll(LINK_TITLE, "Comprueba de dónde salen tus coincidencias")
        .replaceAll("Respuesta del enlace:", "Tu respuesta:");
    expect(normalise(container.innerHTML)).toBe(voter);
  });

  test('answerOwner="voter" is the default copy', () => {
    render(<ResultsBreakdown rows={ROWS} answerOwner="voter" />);
    expect(screen.getByText(INTRO)).toBeTruthy();
  });
});
