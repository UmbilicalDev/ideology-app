import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, test, vi } from "vitest";

import {
  computeMatchScores,
  createPublicApiClient,
  type Answer,
  type FetchLike,
  type HttpResponseLike,
  type ScaleValue,
} from "@ideology-app/core";

import { App } from "../../app/App";
import { datasetVersionJson, electionJson, jsonResponse, textResponse } from "../../test/fetch-mocks";
import { METHODOLOGY_PATH } from "../paths";

const ELECTION_URL = "/api/v1/elections/1";
const VERSION_URL = "/api/v1/dataset-versions/1";

function routes(table: Record<string, () => HttpResponseLike>) {
  return vi.fn<FetchLike>(async (url) => {
    const respond = table[url];
    if (respond === undefined) {
      throw new Error(`unexpected request ${url}`);
    }
    return respond();
  });
}

function happyFetch(statements = 3) {
  return routes({
    [ELECTION_URL]: () => jsonResponse(electionJson()),
    [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements })),
  });
}

function renderAt(path: string, fetch: FetchLike) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
}

async function openQuestionnaire(fetch: FetchLike = happyFetch()) {
  renderAt("/elecciones/1/cuestionario", fetch);
  await screen.findByRole("radiogroup");
}

function heading2() {
  return screen.getByRole("heading", { level: 2 });
}

function radio(name: string) {
  return screen.getByRole("radio", { name }) as HTMLInputElement;
}

function button(name: string) {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

function checkedRadios() {
  return screen.getAllByRole("radio").filter((r) => (r as HTMLInputElement).checked);
}

const LABELS = [
  "Muy en desacuerdo",
  "En desacuerdo",
  "Ni de acuerdo ni en desacuerdo",
  "De acuerdo",
  "Muy de acuerdo",
];

describe("QuestionnairePage", () => {
  test("Scenario 1: loading, then the first Statement with five unchecked radios", async () => {
    const fetch = happyFetch();
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Cuestionario");
    expect(screen.getByRole("status").textContent).toBe("Cargando cuestionario…");

    const group = await screen.findByRole("radiogroup", { name: "Afirmación de prueba 1" });
    expect(screen.getByText("Generales 2023").className).toBe("questionnaire__election");
    expect(screen.getByText("Afirmación 1 de 3")).toBeTruthy();
    const progress = screen.getByRole("progressbar", { name: "Afirmación 1 de 3" });
    expect(progress.getAttribute("value")).toBe("1");
    expect(progress.getAttribute("max")).toBe("3");
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.closest("label")?.textContent?.trim())).toEqual(LABELS);
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(["-2", "-1", "0", "1", "2"]);
    expect(checkedRadios()).toHaveLength(0);
    expect(button("Siguiente").disabled).toBe(true);
    expect(button("Saltar esta afirmación").disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "Anterior" })).toBeNull();
    expect(screen.getByText(/Tus respuestas se quedan en este navegador/).className).toBe(
      "questionnaire__note",
    );
    // Initial load does not move focus.
    expect(document.activeElement).toBe(document.body);
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([ELECTION_URL, VERSION_URL]);
  });

  test("Scenarios 2-5: answer, skip, go back, change and reach the end", async () => {
    const fetch = happyFetch();
    await openQuestionnaire(fetch);

    // Scenario 2: selecting does not advance; Siguiente does, and focuses the heading.
    fireEvent.click(radio("De acuerdo"));
    expect(radio("De acuerdo").checked).toBe(true);
    expect(heading2().textContent).toBe("Afirmación de prueba 1");
    expect(button("Siguiente").disabled).toBe(false);
    fireEvent.click(button("Siguiente"));
    expect(heading2().textContent).toBe("Afirmación de prueba 2");
    expect(screen.getByText("Afirmación 2 de 3")).toBeTruthy();
    expect(checkedRadios()).toHaveLength(0);
    expect(button("Anterior")).toBeTruthy();
    expect(document.activeElement).toBe(heading2());

    // Scenario 3: skip.
    fireEvent.click(button("Saltar esta afirmación"));
    expect(heading2().textContent).toBe("Afirmación de prueba 3");
    expect(screen.getByText("Afirmación 3 de 3")).toBeTruthy();
    expect(document.activeElement).toBe(heading2());

    // Scenario 4: back to the skipped one, then to the answered one, and change it.
    fireEvent.click(button("Anterior"));
    expect(heading2().textContent).toBe("Afirmación de prueba 2");
    expect(checkedRadios()).toHaveLength(0);
    expect(screen.getByText("Has saltado esta afirmación.")).toBeTruthy();
    expect(button("Siguiente").disabled).toBe(false);
    expect(document.activeElement).toBe(heading2());
    fireEvent.click(button("Anterior"));
    expect(heading2().textContent).toBe("Afirmación de prueba 1");
    expect(radio("De acuerdo").checked).toBe(true);
    expect(screen.queryByRole("button", { name: "Anterior" })).toBeNull();
    fireEvent.click(radio("Muy de acuerdo"));
    expect(radio("Muy de acuerdo").checked).toBe(true);
    expect(checkedRadios()).toHaveLength(1);
    fireEvent.click(button("Siguiente"));
    expect(heading2().textContent).toBe("Afirmación de prueba 2");
    expect(screen.getByText("Has saltado esta afirmación.")).toBeTruthy();

    // A value replaces a skip.
    fireEvent.click(radio("En desacuerdo"));
    expect(screen.queryByText("Has saltado esta afirmación.")).toBeNull();
    fireEvent.click(button("Siguiente"));

    // Scenario 5: leave the last Statement with Saltar and reach the end screen.
    expect(heading2().textContent).toBe("Afirmación de prueba 3");
    fireEvent.click(button("Saltar esta afirmación"));
    expect(heading2().textContent).toBe("Tus resultados");
    expect(document.activeElement).toBe(heading2());
    expect(screen.getByText("Has respondido 2 de 3 afirmaciones y has saltado 1.")).toBeTruthy();
    expect(screen.queryByText(/muy pronto/)).toBeNull();
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");

    fireEvent.click(button("Volver a la última afirmación"));
    expect(heading2().textContent).toBe("Afirmación de prueba 3");
    expect(screen.getByText("Has saltado esta afirmación.")).toBeTruthy();
    expect(document.activeElement).toBe(heading2());

    // Saltar on an answered Statement replaces the value with a skip.
    fireEvent.click(button("Anterior"));
    fireEvent.click(button("Saltar esta afirmación"));
    fireEvent.click(button("Anterior"));
    expect(screen.getByText("Has saltado esta afirmación.")).toBeTruthy();
    expect(checkedRadios()).toHaveLength(0);

    // Scenario 8 (jsdom part): only the two loads, and nothing stored.
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([ELECTION_URL, VERSION_URL]);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  test("Scenario 5: leaving the last Statement with Siguiente counts it as answered", async () => {
    await openQuestionnaire(happyFetch(1));
    expect(screen.getByText("Afirmación 1 de 1")).toBeTruthy();
    fireEvent.click(radio("Ni de acuerdo ni en desacuerdo"));
    fireEvent.click(button("Siguiente"));
    expect(screen.getByText("Has respondido 1 de 1 afirmaciones y has saltado 0.")).toBeTruthy();
    fireEvent.click(button("Volver a la última afirmación"));
    expect(radio("Ni de acuerdo ni en desacuerdo").checked).toBe(true);
  });

  test("Scenario 6: each Statement has its own radio name, so no checked state leaks", async () => {
    await openQuestionnaire();
    const firstName = radio("De acuerdo").name;
    expect(firstName).toBe("answer-101");
    fireEvent.click(radio("De acuerdo"));
    fireEvent.click(button("Siguiente"));
    expect(radio("De acuerdo").name).toBe("answer-102");
    expect(screen.getAllByRole("radio").every((r) => r.getAttribute("name") === "answer-102")).toBe(true);
  });

  describe("Important flag", () => {
    function toggle() {
      return button("Importante para mí");
    }

    function pressed() {
      return toggle().getAttribute("aria-pressed");
    }

    test("Scenario 1: the toggle flips on and off without advancing, focus stays on it", async () => {
      await openQuestionnaire();
      const star = toggle();
      expect(star.type).toBe("button");
      expect(pressed()).toBe("false");
      const hint = document.getElementById(star.getAttribute("aria-describedby") ?? "");
      expect(hint?.textContent).toBe(
        "Las afirmaciones importantes cuentan el doble al calcular la afinidad.",
      );
      expect(hint?.className).toBe("questionnaire__hint");
      expect(star.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
      // The hint follows the toggle, and both come before the radiogroup.
      const group = screen.getByRole("radiogroup");
      expect(heading2().compareDocumentPosition(star) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(star.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

      star.focus();
      fireEvent.click(star);
      expect(pressed()).toBe("true");
      expect(toggle().textContent).toBe("Importante para mí");
      expect(document.activeElement).toBe(toggle());
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(screen.getByText("Afirmación 1 de 3")).toBeTruthy();
      expect(button("Siguiente").disabled).toBe(true);
      expect(checkedRadios()).toHaveLength(0);

      fireEvent.click(toggle());
      expect(pressed()).toBe("false");
      expect(document.activeElement).toBe(toggle());
    });

    test("Scenarios 2-4: the flag survives Siguiente, Anterior and Saltar, and works before rating", async () => {
      await openQuestionnaire();

      // Scenario 2.
      fireEvent.click(toggle());
      fireEvent.click(radio("De acuerdo"));
      fireEvent.click(button("Siguiente"));
      expect(heading2().textContent).toBe("Afirmación de prueba 2");
      expect(pressed()).toBe("false");
      fireEvent.click(button("Anterior"));
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(radio("De acuerdo").checked).toBe(true);
      expect(pressed()).toBe("true");

      // Scenario 3.
      fireEvent.click(button("Siguiente"));
      fireEvent.click(toggle());
      fireEvent.click(button("Saltar esta afirmación"));
      expect(heading2().textContent).toBe("Afirmación de prueba 3");
      expect(pressed()).toBe("false");
      fireEvent.click(button("Anterior"));
      expect(screen.getByText("Has saltado esta afirmación.")).toBeTruthy();
      expect(pressed()).toBe("true");
      fireEvent.click(radio("Muy de acuerdo"));
      expect(pressed()).toBe("true");
      fireEvent.click(button("Siguiente"));

      // Scenario 4.
      expect(heading2().textContent).toBe("Afirmación de prueba 3");
      fireEvent.click(toggle());
      fireEvent.click(button("Anterior"));
      fireEvent.click(button("Siguiente"));
      expect(heading2().textContent).toBe("Afirmación de prueba 3");
      expect(checkedRadios()).toHaveLength(0);
      expect(pressed()).toBe("true");
      expect(button("Siguiente").disabled).toBe(true);
    });

    test("Scenario 5: the end screen counts rated Important Statements; Scenario 7 in jsdom", async () => {
      const fetch = happyFetch();
      await openQuestionnaire(fetch);
      const answered = "Has respondido 2 de 3 afirmaciones y has saltado 1.";

      // 1: rated + Important. 2: rated + Important. 3: skipped + Important.
      fireEvent.click(toggle());
      fireEvent.click(radio("De acuerdo"));
      fireEvent.click(button("Siguiente"));
      fireEvent.click(toggle());
      fireEvent.click(radio("En desacuerdo"));
      fireEvent.click(button("Siguiente"));
      fireEvent.click(toggle());
      fireEvent.click(button("Saltar esta afirmación"));
      const summary = screen.getByText(answered);
      const sentence = screen.getByText("Has marcado 2 afirmaciones como importantes.");
      expect(summary.nextElementSibling).toBe(sentence);

      fireEvent.click(button("Volver a la última afirmación"));
      expect(heading2().textContent).toBe("Afirmación de prueba 3");
      expect(pressed()).toBe("true");

      // Unmark Statement 2.
      fireEvent.click(button("Anterior"));
      fireEvent.click(toggle());
      fireEvent.click(button("Siguiente"));
      fireEvent.click(button("Siguiente"));
      expect(screen.getByText("Has marcado 1 afirmación como importante.")).toBeTruthy();

      // Unmark Statement 1 too.
      fireEvent.click(button("Volver a la última afirmación"));
      fireEvent.click(button("Anterior"));
      fireEvent.click(button("Anterior"));
      fireEvent.click(toggle());
      fireEvent.click(button("Siguiente"));
      fireEvent.click(button("Siguiente"));
      fireEvent.click(button("Siguiente"));
      expect(screen.getByText(answered)).toBeTruthy();
      expect(screen.getByText("No has marcado ninguna afirmación como importante.")).toBeTruthy();

      expect(fetch.mock.calls.map((call) => call[0])).toEqual([ELECTION_URL, VERSION_URL]);
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
      expect(document.cookie).toBe("");
    });
  });

  test("Scenario 7: no Published version shows not available after one request", async () => {
    const fetch = routes({
      "/api/v1/elections/2": () =>
        jsonResponse(electionJson({ id: 2, status: "draft", published_dataset_version_id: null })),
    });
    renderAt("/elecciones/2/cuestionario", fetch);
    expect(
      await screen.findByText(
        "El cuestionario de estas elecciones todavía no está disponible. Vuelve a consultarlo más adelante.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  test("Scenario 7: a version with zero Statements shows not available", async () => {
    const fetch = routes({
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 0 })),
    });
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(await screen.findByText(/todavía no está disponible/)).toBeTruthy();
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });

  test("Scenario 7: an unknown Election renders Página no encontrada", async () => {
    const fetch = routes({
      "/api/v1/elections/999": () => jsonResponse({ error: { code: "election_not_found" } }, 404),
    });
    renderAt("/elecciones/999/cuestionario", fetch);
    expect(
      (await screen.findByRole("heading", { level: 1, name: "Página no encontrada" })).textContent,
    ).toBe("Página no encontrada");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  test("Scenario 7: an API error shows the alert, and Reintentar loads again", async () => {
    let fail = true;
    const fetch = routes({
      [ELECTION_URL]: () => (fail ? textResponse(500) : jsonResponse(electionJson())),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 3 })),
    });
    const consoleError = vi.spyOn(console, "error");
    renderAt("/elecciones/1/cuestionario", fetch);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(
      "No se ha podido cargar el cuestionario. Comprueba tu conexión e inténtalo de nuevo.",
    )).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" })).toBeTruthy();

    fail = false;
    fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(screen.getByRole("status").textContent).toBe("Cargando cuestionario…");
    expect(await screen.findByRole("radiogroup", { name: "Afirmación de prueba 1" })).toBeTruthy();
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([ELECTION_URL, ELECTION_URL, VERSION_URL]);
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  test.each<[string, () => HttpResponseLike]>([
    ["a 404 from the Dataset Version", () => jsonResponse({ error: {} }, 404)],
    ["a Dataset Version of another Election", () => jsonResponse(datasetVersionJson({ statements: 3, electionId: 5 }))],
    ["an invalid Dataset Version body", () => jsonResponse({ id: 1 })],
  ])("Scenario 7: %s shows the error alert", async (_label, version) => {
    const fetch = routes({
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: version,
    });
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Página no encontrada")).toBeNull();
  });

  test("Scenario 7: a network failure shows the error alert", async () => {
    const fetch = vi.fn<FetchLike>(async () => {
      throw new TypeError("Failed to fetch");
    });
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(await screen.findByRole("button", { name: "Reintentar" })).toBeTruthy();
  });

  test("the Election's published version id is the one requested", async () => {
    const fetch = routes({
      "/api/v1/elections/4": () => jsonResponse(electionJson({ id: 4, published_dataset_version_id: 9 })),
      "/api/v1/dataset-versions/9": () =>
        jsonResponse(datasetVersionJson({ statements: 2, electionId: 4, id: 9 })),
    });
    renderAt("/elecciones/4/cuestionario", fetch);
    expect(await screen.findByText("Afirmación 1 de 2")).toBeTruthy();
  });

  describe("results", () => {
    const NBSP = " ";
    const LEGEND =
      "Baja cobertura: compartes menos de 5 afirmaciones con ese partido, así que su afinidad " +
      "se basa en pocos datos.";
    const PROMPT =
      "Todavía no se puede calcular tu afinidad: no has respondido ninguna afirmación en la que " +
      "los partidos tengan posición. Responde al menos una para ver los resultados.";
    // The fixture's Party Positions (datasetVersionJson, 6 Statements, ids 101..106).
    const IDS = [101, 102, 103, 104, 105, 106];
    const PARTIES = [
      { partyId: "Uno", positions: IDS.map((statementId) => ({ statementId, value: 1 as const })) },
      {
        partyId: "Dos",
        positions: IDS.map((statementId, i) => ({
          statementId,
          value: i === 0 ? ("no_stance" as const) : (-1 as const),
        })),
      },
    ];

    let currentUrl = "";
    function LocationProbe() {
      const location = useLocation();
      currentUrl = `${location.pathname}${location.search}${location.hash}`;
      return null;
    }

    function renderResults(fetch: FetchLike) {
      return render(
        <MemoryRouter initialEntries={["/elecciones/1/cuestionario"]}>
          <App api={createPublicApiClient({ fetch })} />
          <LocationProbe />
        </MemoryRouter>,
      );
    }

    async function openSix(fetch: FetchLike = happyFetch(6)) {
      const view = renderResults(fetch);
      await screen.findByRole("radiogroup");
      return view;
    }

    type Step = { readonly label: string; readonly important?: boolean } | "skip";

    function walk(steps: readonly Step[]) {
      for (const step of steps) {
        if (step === "skip") {
          fireEvent.click(button("Saltar esta afirmación"));
          continue;
        }
        if (step.important === true) {
          fireEvent.click(button("Importante para mí"));
        }
        fireEvent.click(radio(step.label));
        fireEvent.click(button("Siguiente"));
      }
    }

    function rankingRows() {
      return within(screen.getByRole("list", { name: "Tus resultados" })).getAllByRole("listitem");
    }

    function rowTexts() {
      return rankingRows().map((li) => li.textContent);
    }

    function enginePercent(answers: readonly Answer[]) {
      return computeMatchScores(answers, PARTIES).map((r) => [
        r.partyId,
        r.matchScore === null ? null : Math.round(r.matchScore * 100),
      ]);
    }

    function engineAnswers(values: readonly (ScaleValue | "skip")[], important: readonly number[] = []) {
      return values.map((value, i) => ({
        statementId: IDS[i]!,
        value,
        important: important.includes(IDS[i]!),
      }));
    }

    const AGREE = { label: "De acuerdo" } as const;

    test("Scenario 1: ranking ordered by score, focus on Tus resultados, badge and legend", async () => {
      const fetch = happyFetch(6);
      await openSix(fetch);
      walk([AGREE, AGREE, AGREE, AGREE, AGREE, "skip"]);

      expect(heading2().textContent).toBe("Tus resultados");
      expect(document.activeElement).toBe(heading2());
      expect(screen.getByText("Has respondido 5 de 6 afirmaciones y has saltado 1.")).toBeTruthy();
      expect(
        screen.getByText("Afinidad entre tus respuestas y el programa de cada partido, de mayor a menor."),
      ).toBeTruthy();
      expect(rowTexts()).toEqual([
        `Partido Uno P1 100${NBSP}%5 afirmaciones en común`,
        `Partido Dos P2 50${NBSP}%4 afirmaciones en común Baja cobertura`,
      ]);
      expect(within(rankingRows()[1]!).getByText("Baja cobertura").className).toBe("coverage-badge");
      expect(screen.getByText(LEGEND)).toBeTruthy();
      for (const li of rankingRows()) {
        expect(li.querySelector(".ranking-bar")?.getAttribute("aria-hidden")).toBe("true");
      }
      expect(enginePercent(engineAnswers([1, 1, 1, 1, 1, "skip"]))).toEqual([
        ["Uno", 100],
        ["Dos", 50],
      ]);
      expect(screen.queryByText(PROMPT)).toBeNull();
      expect(button("Revisar mis respuestas").className).toBe("button-primary");
      expect(button("Volver a la última afirmación").className).toBe("button-secondary");
      expect(
        screen.getByText(
          "Esto no es una recomendación de voto: solo compara tus respuestas con lo que dicen los " +
            "programas, según una inteligencia artificial que puede equivocarse.",
        ),
      ).toBeTruthy();
      expect(
        screen.getByText(
          "Tus respuestas siguen solo en este navegador: si recargas la página, vuelves atrás con " +
            "el navegador o sales de aquí, se pierden.",
        ).className,
      ).toBe("questionnaire__note");
      expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
    });

    test("Scenario 2: a tie on the displayed percentage is ordered by name", async () => {
      await openSix();
      const neutral = { label: "Ni de acuerdo ni en desacuerdo" } as const;
      walk([neutral, neutral, neutral, neutral, neutral, neutral]);
      expect(rowTexts()).toEqual([
        `Partido Dos P2 75${NBSP}%5 afirmaciones en común`,
        `Partido Uno P1 75${NBSP}%6 afirmaciones en común`,
      ]);
      expect(screen.queryByText(LEGEND)).toBeNull();
      expect(enginePercent(engineAnswers([0, 0, 0, 0, 0, 0]))).toEqual([
        ["Uno", 75],
        ["Dos", 75],
      ]);
    });

    test("Scenario 3: an Important Statement weighs double", async () => {
      await openSix();
      walk([AGREE, AGREE, AGREE, AGREE, AGREE, { label: "Muy en desacuerdo", important: true }]);
      expect(rowTexts()).toEqual([
        `Partido Uno P1 79${NBSP}%6 afirmaciones en común`,
        `Partido Dos P2 58${NBSP}%5 afirmaciones en común`,
      ]);
      expect(screen.getByText("Has marcado 1 afirmación como importante.")).toBeTruthy();
      expect(enginePercent(engineAnswers([1, 1, 1, 1, 1, -2], [106]))).toEqual([
        ["Uno", 79],
        ["Dos", 58],
      ]);
    });

    test("Scenario 4: everything skipped shows the prompt; rating one shows a ranking", async () => {
      await openSix();
      walk(["skip", "skip", "skip", "skip", "skip", "skip"]);
      expect(heading2().textContent).toBe("Tus resultados");
      expect(screen.getByText(PROMPT)).toBeTruthy();
      expect(screen.queryByRole("list")).toBeNull();
      expect(screen.queryByText(/%/)).toBeNull();
      expect(screen.queryByText(LEGEND)).toBeNull();
      expect(
        screen.getByRole("link", { name: "Cómo se calcula la afinidad (se abre en una pestaña nueva)" }),
      ).toBeTruthy();

      fireEvent.click(button("Revisar mis respuestas"));
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(document.activeElement).toBe(heading2());
      expect(screen.getByText("Has saltado esta afirmación.")).toBeTruthy();
      fireEvent.click(radio("Muy de acuerdo"));
      fireEvent.click(button("Siguiente"));
      walk(["skip", "skip", "skip", "skip", "skip"]);
      expect(screen.queryByText(PROMPT)).toBeNull();
      // Statement 1: Uno +1 (agreement 0.75); Dos has no stance there, so no score.
      expect(rowTexts()).toEqual([
        `Partido Uno P1 75${NBSP}%1 afirmación en común Baja cobertura`,
        "Partido Dos P2 Sin afirmaciones en común0 afirmaciones en común Baja cobertura",
      ]);
    });

    test("Scenario 5: going back keeps every Answer and flag, and the same ranking comes back", async () => {
      await openSix();
      walk([
        { label: "De acuerdo", important: true },
        AGREE,
        AGREE,
        AGREE,
        AGREE,
        { label: "Muy en desacuerdo", important: true },
      ]);
      const before = rowTexts();

      fireEvent.click(button("Volver a la última afirmación"));
      expect(heading2().textContent).toBe("Afirmación de prueba 6");
      expect(document.activeElement).toBe(heading2());
      expect(radio("Muy en desacuerdo").checked).toBe(true);
      expect(button("Importante para mí").getAttribute("aria-pressed")).toBe("true");
      fireEvent.click(button("Siguiente"));
      expect(rowTexts()).toEqual(before);

      fireEvent.click(button("Revisar mis respuestas"));
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(document.activeElement).toBe(heading2());
      expect(radio("De acuerdo").checked).toBe(true);
      expect(button("Importante para mí").getAttribute("aria-pressed")).toBe("true");
      for (let i = 0; i < 6; i += 1) {
        fireEvent.click(button("Siguiente"));
      }
      expect(heading2().textContent).toBe("Tus resultados");
      expect(rowTexts()).toEqual(before);
    });

    test("Scenario 6: the methodology link opens METHODOLOGY_PATH in a new tab, on results and prompt", async () => {
      await openSix();
      walk([AGREE, "skip", "skip", "skip", "skip", "skip"]);
      const name = "Cómo se calcula la afinidad (se abre en una pestaña nueva)";
      for (const pass of ["ranking", "prompt"]) {
        if (pass === "prompt") {
          fireEvent.click(button("Revisar mis respuestas"));
          walk(["skip", "skip", "skip", "skip", "skip", "skip"]);
          expect(screen.getByText(PROMPT)).toBeTruthy();
        } else {
          expect(screen.getByRole("list", { name: "Tus resultados" })).toBeTruthy();
        }
        const link = screen.getByRole("link", { name });
        expect(link.getAttribute("href")).toBe(METHODOLOGY_PATH);
        expect(link.getAttribute("target")).toBe("_blank");
        expect(link.getAttribute("rel")).toContain("noopener");
        expect(link.className).toBe("text-link");
      }
    });

    test("Scenario 7: Answers never leave the component; a reload starts over", async () => {
      const fetch = happyFetch(6);
      const view = await openSix(fetch);
      walk([AGREE, { label: "Muy de acuerdo", important: true }, "skip", AGREE, AGREE, AGREE]);
      expect(screen.getByRole("list", { name: "Tus resultados" })).toBeTruthy();
      expect(currentUrl).toBe("/elecciones/1/cuestionario");
      expect(fetch.mock.calls.map((call) => call[0])).toEqual([ELECTION_URL, VERSION_URL]);
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
      expect(document.cookie).toBe("");

      view.unmount();
      await openSix(fetch);
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(checkedRadios()).toHaveLength(0);
      expect(button("Importante para mí").getAttribute("aria-pressed")).toBe("false");
    });
  });
});
