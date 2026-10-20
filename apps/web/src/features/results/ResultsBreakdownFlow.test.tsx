import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike, type HttpResponseLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { datasetVersionJson, electionJson, jsonResponse } from "../../test/fetch-mocks";

// The results breakdown through the whole App, with the 6-Statement fixture
// (ids 101..106): Partido Uno +1 everywhere with Evidence from a URL document
// (page 3), Partido Dos no stance on Statement 1 and -1 elsewhere with
// Evidence from an upload (page 1).

const ELECTION_URL = "/api/v1/elections/1";
const VERSION_URL = "/api/v1/dataset-versions/1";
const UNO_HREF = "https://example.org/uno.pdf#page=3";
const LINK_NAME = "Ver en el programa, página 3 (se abre en una pestaña nueva)";
const UPLOAD_SENTENCE = "Página 1 del programa electoral. Este documento no tiene un enlace público.";
const NO_STANCE_SENTENCE =
  "El programa de este partido no trata esta afirmación, así que no cuenta para su afinidad.";
const PROMPT =
  "Todavía no se puede calcular tu afinidad: no has respondido ninguna afirmación en la que " +
  "los partidos tengan posición. Responde al menos una para ver los resultados.";

type PartyJson = { positions: { evidence: Record<string, unknown> | null }[] };

function versionWithUrl(): Record<string, unknown> {
  const body = datasetVersionJson({ statements: 6 });
  const [uno] = body["parties"] as PartyJson[];
  for (const position of uno!.positions) {
    position.evidence = {
      quote: "Cita del programa de Partido Uno.",
      page: 3,
      url: "https://example.org/uno.pdf",
      source_document_id: 2,
    };
  }
  return body;
}

function routes(table: Record<string, () => HttpResponseLike>) {
  return vi.fn<FetchLike>(async (url) => {
    const respond = table[url];
    if (respond === undefined) {
      throw new Error(`unexpected request ${url}`);
    }
    return respond();
  });
}

function happyFetch() {
  return routes({
    [ELECTION_URL]: () => jsonResponse(electionJson()),
    [VERSION_URL]: () => jsonResponse(versionWithUrl()),
  });
}

let currentUrl = "";
function LocationProbe() {
  const location = useLocation();
  currentUrl = `${location.pathname}${location.search}${location.hash}`;
  return null;
}

function renderAt(path: string, fetch: FetchLike) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createPublicApiClient({ fetch })} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

async function openSix(fetch: FetchLike = happyFetch()) {
  renderAt("/elecciones/1/cuestionario", fetch);
  await screen.findByRole("radiogroup");
}

function button(name: string) {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

type Step = { readonly label: string; readonly important?: boolean } | "skip" | "flag-skip";

function walk(steps: readonly Step[]) {
  for (const step of steps) {
    if (step === "skip" || step === "flag-skip") {
      if (step === "flag-skip") {
        fireEvent.click(button("Importante para mí"));
      }
      fireEvent.click(button("Saltar esta afirmación"));
      continue;
    }
    if (step.important === true) {
      fireEvent.click(button("Importante para mí"));
    }
    fireEvent.click(screen.getByRole("radio", { name: step.label }));
    fireEvent.click(button("Siguiente"));
  }
}

const AGREE = { label: "De acuerdo" } as const;
// Scenario 1's walk: 1-4 De acuerdo (2 Important), skip 5, flag then skip 6.
const SCENARIO_1: readonly Step[] = [AGREE, { label: "De acuerdo", important: true }, AGREE, AGREE, "skip", "flag-skip"];

function breakdownRows(): HTMLElement[] {
  return Array.from(screen.getByRole("list", { name: "Detalle por afirmación" }).children) as HTMLElement[];
}

function partyNames(row: HTMLElement): string[] {
  return Array.from(row.querySelectorAll(".position__name")).map((el) => el.textContent ?? "");
}

function rankingNames(): string[] {
  return within(screen.getByRole("list", { name: "Tus resultados" }))
    .getAllByRole("listitem")
    .map((li) => li.querySelector(".ranking-row__name")?.textContent ?? "");
}

function item(row: HTMLElement, party: string): HTMLDetailsElement {
  const details = Array.from(row.querySelectorAll<HTMLDetailsElement>("details")).find(
    (d) => d.querySelector(".position__name")?.textContent === party,
  );
  if (details === undefined) {
    throw new Error(`no item for ${party}`);
  }
  return details;
}

// jsdom implements the <summary> activation behaviour: a click toggles the
// parent <details>.
function open(details: HTMLDetailsElement) {
  fireEvent.click(details.querySelector("summary")!);
  expect(details.open).toBe(true);
}

describe("results breakdown", () => {
  test("Scenario 1: one row per Statement with the Voter's Answer, skip and Important", async () => {
    await openSix();
    walk(SCENARIO_1);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Tus resultados");
    expect(
      screen.getByRole("heading", { level: 3, name: "Detalle por afirmación" }),
    ).toBeTruthy();
    const rows = breakdownRows();
    expect(rows).toHaveLength(6);
    rows.forEach((row, i) => {
      expect(row.querySelector(".breakdown-row__number")?.textContent).toBe(`Afirmación ${i + 1}`);
      expect(within(row).getByRole("heading", { level: 4 }).textContent).toBe(`Afirmación de prueba ${i + 1}`);
    });
    const answer = (i: number) => rows[i]!.querySelector(".breakdown-row__answer")!.textContent;
    expect(answer(0)).toBe("Tu respuesta: De acuerdo");
    expect(answer(1)).toBe("Tu respuesta: De acuerdo Importante (cuenta el doble)");
    expect(answer(4)).toBe("Tu respuesta: Saltada (no cuenta para la afinidad)");
    expect(answer(5)).toBe("Tu respuesta: Saltada (no cuenta para la afinidad)");
    expect(screen.getAllByText("Importante (cuenta el doble)")).toHaveLength(1);
    // The section sits after the methodology link and before the privacy note.
    const section = screen.getByRole("region", { name: "Detalle por afirmación" });
    const methodology = screen.getByRole("link", {
      name: "Cómo se calcula la afinidad (se abre en una pestaña nueva)",
    });
    const note = screen.getByText(/Tus respuestas siguen solo en este navegador/);
    expect(methodology.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(section.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("Scenario 2: Parties follow the ranking order in every row, and follow it when it changes", async () => {
    await openSix();
    walk(SCENARIO_1);
    expect(rankingNames()).toEqual(["Partido Uno", "Partido Dos"]);
    for (const row of breakdownRows()) {
      expect(partyNames(row)).toEqual(["Partido Uno", "Partido Dos"]);
    }

    fireEvent.click(button("Revisar mis respuestas"));
    walk(Array.from({ length: 6 }, () => ({ label: "Muy en desacuerdo" })));
    expect(rankingNames()).toEqual(["Partido Dos", "Partido Uno"]);
    for (const row of breakdownRows()) {
      expect(partyNames(row)).toEqual(["Partido Dos", "Partido Uno"]);
      expect(row.querySelector(".breakdown-row__answer")?.textContent).toMatch(
        /^Tu respuesta: Muy en desacuerdo/,
      );
    }
  });

  test("Scenario 3: opening a URL-document stance shows the quote and a new-tab page link", async () => {
    await openSix();
    walk(SCENARIO_1);
    const uno = item(breakdownRows()[0]!, "Partido Uno");
    expect(uno.open).toBe(false);
    expect(uno.querySelector("summary")?.textContent).toBe("Partido Uno P1 De acuerdo");
    open(uno);
    const quote = uno.querySelector("blockquote.evidence__quote");
    expect(quote?.textContent).toBe("Cita del programa de Partido Uno.");
    const link = within(uno).getByRole("link", { name: LINK_NAME });
    expect(link.getAttribute("href")).toBe(UNO_HREF);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  test("Scenario 4: an uploaded document shows the quote and the page, no link", async () => {
    await openSix();
    walk(SCENARIO_1);
    const dos = item(breakdownRows()[1]!, "Partido Dos");
    expect(dos.querySelector("summary")?.textContent).toBe("Partido Dos P2 En desacuerdo");
    open(dos);
    expect(dos.querySelector("blockquote.evidence__quote")?.textContent).toBe("Cita.");
    expect(within(dos).getByText(UPLOAD_SENTENCE)).toBeTruthy();
    expect(dos.querySelector("a")).toBeNull();
  });

  test("Scenario 5: no stance is labelled and opens to the no-stance sentence", async () => {
    await openSix();
    walk(SCENARIO_1);
    const dos = item(breakdownRows()[0]!, "Partido Dos");
    expect(dos.querySelector("summary")?.textContent).toBe("Partido Dos P2 Sin posición en el programa");
    open(dos);
    expect(within(dos).getByText(NO_STANCE_SENTENCE)).toBeTruthy();
    expect(dos.querySelector("blockquote")).toBeNull();
    expect(dos.querySelector("a")).toBeNull();
  });

  test("Scenario 6: everything skipped shows the prompt and still the breakdown, Parties by name", async () => {
    await openSix();
    walk(["skip", "skip", "skip", "skip", "skip", "skip"]);
    expect(screen.getByText(PROMPT)).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Tus resultados" })).toBeNull();
    const rows = breakdownRows();
    expect(rows).toHaveLength(6);
    for (const row of rows) {
      expect(partyNames(row)).toEqual(["Partido Dos", "Partido Uno"]);
      expect(row.querySelector(".breakdown-row__answer")?.textContent).toBe(
        "Tu respuesta: Saltada (no cuenta para la afinidad)",
      );
    }
  });

  test("Scenario 7: nothing leaves the browser", async () => {
    const fetch = happyFetch();
    await openSix(fetch);
    walk(SCENARIO_1);
    open(item(breakdownRows()[0]!, "Partido Uno"));
    open(item(breakdownRows()[1]!, "Partido Dos"));
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([ELECTION_URL, VERSION_URL]);
    expect(currentUrl).toBe("/elecciones/1/cuestionario");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });
});
