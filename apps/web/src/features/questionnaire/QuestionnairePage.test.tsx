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
import {
  datasetVersionJson,
  electionJson,
  jsonResponse,
  partyLogoUrl,
  recordImageRequests,
  textResponse,
} from "../../test/fetch-mocks";
import { textWithoutLogos } from "../../test/text";
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

// The end screen has no shortcut to the last Statement: review from the
// first and step forward to the last of `count`.
function backToLast(count: number) {
  fireEvent.click(button("Revisar mis respuestas"));
  for (let i = 1; i < count; i += 1) {
    fireEvent.click(button("Siguiente"));
  }
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

const LOSS_NOTE = /Tus respuestas siguen solo en este navegador/;

describe("QuestionnairePage", () => {
  test("Scenario 1: loading, then the first Statement with five unchecked radios", async () => {
    const fetch = happyFetch();
    renderAt("/elecciones/1/cuestionario", fetch);
    // Focus shell: no sidebar, only the brand and Salir.
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.getByRole("link", { name: "Salir" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Cuestionario");
    expect(screen.getByRole("status").textContent).toBe("Cargando cuestionario…");

    const group = await screen.findByRole("radiogroup", { name: "Afirmación de prueba 1" });
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Generales 2023");
    expect(h1.className).toBe("questionnaire__election");
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
    expect(screen.getByText("Muestra evaluada: 2/3 afirmaciones contestadas")).toBeTruthy();
    expect(screen.queryByText(/muy pronto/)).toBeNull();
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByRole("link", { name: "Volver al inicio" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Volver a la última afirmación" })).toBeNull();
    expect(screen.getByRole("link", { name: "IdeologiApp, ir al inicio" }).getAttribute("href")).toBe("/");

    backToLast(3);
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
    expect(screen.getByText("Muestra evaluada: 1/1 afirmaciones contestadas")).toBeTruthy();
    backToLast(1);
    expect(radio("Ni de acuerdo ni en desacuerdo").checked).toBe(true);
  });

  test("the controls read Anterior, Saltar, Siguiente and every option has a leading icon", async () => {
    await openQuestionnaire();
    const controls = () =>
      Array.from(document.querySelectorAll<HTMLButtonElement>(".step-controls button")).map(
        (b) => [b.textContent, b.className, b.firstElementChild?.tagName.toLowerCase()],
      );
    // First Statement: no Anterior, so Saltar and Siguiente share the row.
    expect(controls()).toEqual([
      ["Saltar esta afirmación", "button-secondary", "svg"],
      ["Siguiente", "button-primary", "span"],
    ]);
    expect(button("Siguiente").lastElementChild?.tagName.toLowerCase()).toBe("svg");
    fireEvent.click(button("Saltar esta afirmación"));
    expect(controls()).toEqual([
      ["Anterior", "button-secondary", "svg"],
      ["Saltar esta afirmación", "button-secondary", "svg"],
      ["Siguiente", "button-primary", "span"],
    ]);
    for (const label of LABELS) {
      const option = radio(label).closest("label")!;
      expect(option.querySelector("svg.scale-option__icon")?.getAttribute("aria-hidden")).toBe("true");
    }
  });

  test("the Statement slides in the way the Voter moved; the progress bar is kept", async () => {
    await openQuestionnaire();
    const step = () => document.querySelector(".statement-step")!;
    const progress = document.querySelector("progress");
    // No transition on the initial load.
    expect(step().hasAttribute("data-enter")).toBe(false);
    fireEvent.click(button("Saltar esta afirmación"));
    expect(step().getAttribute("data-enter")).toBe("forward");
    fireEvent.click(radio("De acuerdo"));
    fireEvent.click(button("Siguiente"));
    expect(step().getAttribute("data-enter")).toBe("forward");
    const third = step();
    fireEvent.click(button("Anterior"));
    expect(step().getAttribute("data-enter")).toBe("back");
    // A new block per Statement (so the animation replays), the same bar (so its width animates).
    expect(step()).not.toBe(third);
    expect(document.querySelector("progress")).toBe(progress);
  });

  test("turning Importante para mí on glows once; turning it off does not", async () => {
    await openQuestionnaire();
    const star = button("Importante para mí");
    fireEvent.click(star);
    expect(star.classList.contains("important-toggle--flash")).toBe(true);
    fireEvent.click(star);
    expect(star.classList.contains("important-toggle--flash")).toBe(false);
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

  test("the AI/privacy disclosure card follows the scale and is absent on the end screen", async () => {
    await openQuestionnaire();
    const disclosure = screen.getByRole("region", {
      name: "Transparencia algorítmica y privacidad garantizada",
    });
    const title = within(disclosure).getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Transparencia algorítmica y privacidad garantizada");
    const note = within(disclosure).getByText(/Tus respuestas se quedan en este navegador/);
    expect(note.tagName).toBe("P");
    expect(note.className).toBe("questionnaire__note");
    expect(note.textContent).toBe(
      "Las afirmaciones las ha generado una inteligencia artificial a partir de los programas " +
        "electorales. Tus respuestas se quedan en este navegador: no se envían a ningún servidor y " +
        "se pierden si recargas o sales de la página.",
    );
    const icons = disclosure.querySelectorAll("svg");
    expect(icons).toHaveLength(1);
    expect(icons[0]?.getAttribute("aria-hidden")).toBe("true");
    const group = screen.getByRole("radiogroup");
    expect(group.compareDocumentPosition(disclosure) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(button("Saltar esta afirmación"));
    }
    expect(heading2().textContent).toBe("Tus resultados");
    expect(
      screen.queryByRole("region", { name: "Transparencia algorítmica y privacidad garantizada" }),
    ).toBeNull();
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
      // A tooltip on hover or keyboard focus (CSS), always the description.
      expect(hint?.className).toBe("questionnaire__hint important-hint");
      expect(hint?.getAttribute("role")).toBe("tooltip");
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
      const answered = "Muestra evaluada: 2/3 afirmaciones contestadas";

      // 1: rated + Important. 2: rated + Important. 3: skipped + Important.
      fireEvent.click(toggle());
      fireEvent.click(radio("De acuerdo"));
      fireEvent.click(button("Siguiente"));
      fireEvent.click(toggle());
      fireEvent.click(radio("En desacuerdo"));
      fireEvent.click(button("Siguiente"));
      fireEvent.click(toggle());
      fireEvent.click(button("Saltar esta afirmación"));
      const summary = screen.getByRole("region", { name: answered });
      expect(within(summary).getByText("Has saltado 1 afirmación.")).toBeTruthy();
      const sentence = within(summary).getByText("Has marcado 2 afirmaciones como importantes.");
      expect(sentence.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
      expect(sentence.getAttribute("data-marked")).toBe("true");
      // The donut shows the answered share, 2 of 3; the text carries the numbers.
      const donut = summary.querySelector(".summary-donut")!;
      expect(donut.getAttribute("aria-hidden")).toBe("true");
      expect(donut.textContent).toBe("67\u00a0%");

      backToLast(3);
      expect(heading2().textContent).toBe("Afirmación de prueba 3");
      expect(pressed()).toBe("true");

      // Unmark Statement 2.
      fireEvent.click(button("Anterior"));
      fireEvent.click(toggle());
      fireEvent.click(button("Siguiente"));
      fireEvent.click(button("Siguiente"));
      expect(screen.getByText("Has marcado 1 afirmación como importante.")).toBeTruthy();

      // Unmark Statement 1 too.
      fireEvent.click(button("Revisar mis respuestas"));
      fireEvent.click(toggle());
      fireEvent.click(button("Siguiente"));
      fireEvent.click(button("Siguiente"));
      fireEvent.click(button("Siguiente"));
      expect(screen.getByText(answered)).toBeTruthy();
      const none = screen.getByText("No has marcado ninguna afirmación como importante.");
      expect(none.getAttribute("data-marked")).toBe("false");

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

  test("Party logos are preloaded in Party order before the first Answer, never in ranking order", async () => {
    const { srcs } = recordImageRequests();
    const fetch = routes({
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 3, logos: true })),
    });
    await openQuestionnaire(fetch);
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(2)]);
    expect(document.querySelector(".party-logo")).toBeNull();

    // Disagreeing with everything ranks Partido Dos first.
    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(radio("Muy en desacuerdo"));
      fireEvent.click(button("Siguiente"));
    }
    const ranking = Array.from(document.querySelectorAll(".ranking-row img"), (img) =>
      img.getAttribute("src"),
    );
    expect(ranking).toEqual([partyLogoUrl(2), partyLogoUrl(1)]);
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(2)]);
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([ELECTION_URL, VERSION_URL]);
  });

  describe("results", () => {
    const NBSP = " ";
    const LEGEND =
      "Compartes menos de 5 afirmaciones con este partido, así que su afinidad se basa en pocos " +
      "datos.";
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
      return rankingRows().map(textWithoutLogos);
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
      expect(screen.getByText("Muestra evaluada: 5/6 afirmaciones contestadas")).toBeTruthy();
      expect(
        screen.getByText("Afinidad entre tus respuestas y el programa de cada partido, de mayor a menor."),
      ).toBeTruthy();
      expect(rowTexts()).toEqual([
        `Partido Uno P1 100${NBSP}%5 afirmaciones en común`,
        `Partido Dos P2 50${NBSP}%4 afirmaciones en común Baja cobertura${LEGEND}`,
      ]);
      const chip = within(rankingRows()[1]!).getByRole("button", { name: "Baja cobertura" });
      expect(chip.className).toBe("coverage-badge");
      // The explanation is the chip's tooltip, not a legend under the ranking.
      expect(document.getElementById(chip.getAttribute("aria-describedby")!)?.textContent).toBe(LEGEND);
      expect(screen.getAllByText(LEGEND)).toHaveLength(1);
      expect(screen.getAllByText(LEGEND)[0]!.getAttribute("role")).toBe("tooltip");
      for (const li of rankingRows()) {
        expect(li.querySelector(".ranking-bar")?.getAttribute("aria-hidden")).toBe("true");
      }
      expect(enginePercent(engineAnswers([1, 1, 1, 1, 1, "skip"]))).toEqual([
        ["Uno", 100],
        ["Dos", 50],
      ]);
      expect(screen.queryByText(PROMPT)).toBeNull();
      expect(button("Revisar mis respuestas").className).toBe("button-primary");
      // Revisar sits right after the summary, before the ranking and the share card.
      const summary = screen.getByText(/^Muestra evaluada:/).closest(".results-dashboard > *");
      expect(summary?.nextElementSibling).toBe(button("Revisar mis respuestas").parentElement);
      expect(screen.queryByRole("button", { name: "Volver a la última afirmación" })).toBeNull();
      // The warning is no longer a card: an alert button at the top right of
      // the ranking shows it inside the ranking card.
      const ranking = screen.getByRole("region", { name: "Afinidad por partido" });
      const warning = within(ranking).getByText(
        "Esto no es una recomendación de voto: solo compara tus respuestas con lo que dicen los " +
          "programas, según una inteligencia artificial que puede equivocarse.",
      );
      expect(warning.hidden).toBe(true);
      expect(document.querySelector(".notice-card")).toBeNull();
      const alert = within(ranking).getByRole("button", { name: "Aviso sobre estos resultados" });
      expect(alert.getAttribute("aria-controls")).toBe(warning.id);
      expect(alert.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(alert);
      expect([alert.getAttribute("aria-expanded"), warning.hidden]).toEqual(["true", false]);
      fireEvent.click(alert);
      expect(warning.hidden).toBe(true);
      // No loss note and no home button: `Salir` and the brand in the top bar go home.
      expect(screen.queryByText(LOSS_NOTE)).toBeNull();
      expect(screen.queryByRole("link", { name: "Volver al inicio" })).toBeNull();
      expect(screen.queryByRole("link", { name: "Ir al inicio" })).toBeNull();
      expect(button("Revisar mis respuestas").nextElementSibling).toBeNull();
      expect(screen.getByRole("region", { name: "Comprueba de dónde salen tus coincidencias" })).toBeTruthy();
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
      expect(screen.queryByRole("list", { name: "Tus resultados" })).toBeNull();
      // Only the summary donut shows a percentage.
      expect(screen.getAllByText(/%/).map((element) => element.className)).toEqual([
        "summary-donut__label",
      ]);
      expect(screen.queryByText(LEGEND)).toBeNull();
      expect(
        screen.getByRole("link", { name: "Cómo se calcula la afinidad (se abre en una pestaña nueva)" }),
      ).toBeTruthy();
      expect(screen.queryByText(LOSS_NOTE)).toBeNull();

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
        `Partido Uno P1 75${NBSP}%1 afirmación en común Baja cobertura${LEGEND}`,
        `Partido Dos P2 Sin afirmaciones en común0 afirmaciones en común Baja cobertura${LEGEND}`,
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

      backToLast(6);
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

    test("feedback-dialog Scenario 7: sending feedback keeps the Answers, the URL and history", async () => {
      const fetch = routes({
        [ELECTION_URL]: () => jsonResponse(electionJson()),
        [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 6 })),
        "/api/v1/feedback": () => jsonResponse({ status: "ok" }, 201),
      });
      await openSix(fetch);
      walk([AGREE, AGREE, AGREE, AGREE, AGREE, { label: "Muy de acuerdo", important: true }]);
      const before = {
        ranking: rowTexts(),
        summary: screen.getByText(/Muestra evaluada:/).textContent,
        url: currentUrl,
        history: window.history.length,
      };

      // Placement: right after the share card.
      const feedback = button("Danos tu opinión");
      expect(feedback.className).toBe("button-secondary");
      expect(document.querySelector(".results-dashboard .share-card")?.nextElementSibling).toBe(
        feedback.parentElement,
      );

      fireEvent.click(feedback);
      const dialog = screen.getByRole("dialog", { name: "Ayúdanos a mejorar" });
      fireEvent.change(within(dialog).getByRole("textbox", { name: "Tu opinión" }), {
        target: { value: "Interesante" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Enviar" }));
      await within(dialog).findByText("¡Gracias por tu opinión!");
      fireEvent.click(within(dialog).getAllByRole("button", { name: "Cerrar" })[1]!);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.activeElement).toBe(button("Danos tu opinión"));

      const posts = fetch.mock.calls.filter(([url]) => url === "/api/v1/feedback");
      expect(posts).toHaveLength(1);
      expect(posts[0]![1]?.method).toBe("POST");
      const body = JSON.parse(String(posts[0]![1]?.body)) as Record<string, unknown>;
      expect(body).toEqual({ message: "Interesante", origin: "results" });
      expect(fetch.mock.calls.map((call) => call[0])).toEqual([
        ELECTION_URL,
        VERSION_URL,
        "/api/v1/feedback",
      ]);

      expect({
        ranking: rowTexts(),
        summary: screen.getByText(/Muestra evaluada:/).textContent,
        url: currentUrl,
        history: window.history.length,
      }).toEqual(before);
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);

      backToLast(6);
      expect(heading2().textContent).toBe("Afirmación de prueba 6");
      expect(radio("Muy de acuerdo").checked).toBe(true);
      expect(button("Importante para mí").getAttribute("aria-pressed")).toBe("true");
    });
  });
});
