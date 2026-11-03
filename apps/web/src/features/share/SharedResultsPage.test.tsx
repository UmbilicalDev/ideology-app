import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike, type HttpResponseLike } from "@ideology-app/core";

import { App } from "../../app/App";
import {
  datasetVersionJson,
  electionJson,
  jsonResponse,
  partyLogoUrl,
  recordImageRequests,
  textResponse,
} from "../../test/fetch-mocks";
import { SHARED_RESULTS_TITLE } from "./SharedResultsPage";

const ELECTION_URL = "/api/v1/elections/1";
const VERSION_URL = "/api/v1/dataset-versions/1";
const LINK = "/resultados#v1-1-dddddA";

const MISSING = "Este enlace no contiene ningún resultado. Comprueba que lo has copiado entero.";
const INVALID =
  "Este enlace no es válido o está incompleto. Comprueba que lo has copiado entero o pide que " +
  "te lo envíen de nuevo.";
const UNSUPPORTED =
  "Este enlace se creó con una versión más reciente de esta web. Recarga la página para abrirlo.";
const NOT_FOUND = "No encontramos el cuestionario de este enlace. Puede que ya no esté disponible.";
const ERROR = "No se ha podido cargar el resultado. Comprueba tu conexión e inténtalo de nuevo.";
const SUPERSEDED =
  "Este resultado se calculó con una versión anterior del cuestionario de estas elecciones y se " +
  "muestra tal como era. El cuestionario actual puede tener otras afirmaciones y otras posiciones.";
const NOTE =
  "Este resultado se calcula en tu navegador a partir del propio enlace: las respuestas van tras " +
  "el símbolo «#» y no se envían a ningún servidor. Para volver a verlo, guarda el enlace.";

type Responder = () => HttpResponseLike | Promise<HttpResponseLike>;

function routes(table: Record<string, Responder>) {
  return vi.fn<FetchLike>(async (url) => {
    const respond = table[url];
    if (respond === undefined) {
      throw new Error(`unexpected request ${url}`);
    }
    return respond();
  });
}

function sixStatements(election: Record<string, unknown> = {}) {
  return routes({
    [ELECTION_URL]: () => jsonResponse(electionJson(election)),
    [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 6 })),
  });
}

let currentLocation = "";

function LocationProbe() {
  const location = useLocation();
  currentLocation = `${location.pathname}${location.search}${location.hash}`;
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

function urls(fetch: ReturnType<typeof vi.fn<FetchLike>>): string[] {
  return fetch.mock.calls.map((call) => call[0]);
}

function rankingTexts(): string[] {
  return Array.from(document.querySelectorAll(".ranking-row")).map((li) => li.textContent ?? "");
}

function breakdownTexts(): string[] {
  return Array.from(document.querySelectorAll(".breakdown-row")).map((li) =>
    (li.textContent ?? "").replace("Respuesta del enlace:", "Tu respuesta:"),
  );
}

async function ready() {
  return screen.findByRole("heading", { level: 2, name: "Afinidad con cada partido" });
}

let consoleSpies: ReturnType<typeof vi.spyOn>[] = [];

beforeEach(() => {
  consoleSpies = (["error", "warn"] as const).map((m) => vi.spyOn(console, m));
});

afterEach(() => {
  for (const spy of consoleSpies) {
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  }
  currentLocation = "";
});

describe("SharedResultsPage", () => {
  test("Scenario 1: the shared link shows the end screen's ranking and breakdown", async () => {
    // The end screen after answering De acuerdo ×5, then Muy en desacuerdo marked Important.
    const endScreen = renderAt("/elecciones/1/cuestionario", sixStatements());
    await screen.findByRole("radiogroup");
    for (let i = 0; i < 5; i += 1) {
      fireEvent.click(screen.getByRole("radio", { name: "De acuerdo" }));
      fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Importante para mí" }));
    fireEvent.click(screen.getByRole("radio", { name: "Muy en desacuerdo" }));
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Tus resultados");
    const endRanking = rankingTexts();
    const endBreakdown = breakdownTexts();
    expect(endRanking).toHaveLength(2);
    expect(endBreakdown).toHaveLength(6);
    endScreen.unmount();

    const fetch = sixStatements();
    renderAt(LINK, fetch);
    expect(screen.getByRole("status").textContent).toBe("Cargando resultado…");
    await ready();
    expect(urls(fetch)).toEqual([VERSION_URL, ELECTION_URL]);
    expect(rankingTexts()).toEqual(endRanking);
    expect(breakdownTexts()).toEqual(endBreakdown);
    expect(screen.getByText("Generales 2023").className).toBe("questionnaire__election");
    expect(screen.getByText("Muestra evaluada: 6/6 afirmaciones contestadas")).toBeTruthy();
    expect(screen.getByText("Se marcó 1 afirmación como importante.")).toBeTruthy();
    expect(
      screen.getByText(
        "Afinidad entre las respuestas de este enlace y el programa de cada partido, de mayor a menor.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("list", { name: "Afinidad con cada partido" })).toBeTruthy();
    // The warning sits in the ranking card behind the alert button.
    const warning = screen.getByText(
      "Esto no es una recomendación de voto: solo compara estas respuestas con lo que dicen los " +
        "programas, según una inteligencia artificial que puede equivocarse.",
    );
    expect(warning.hidden).toBe(true);
    expect(warning.closest('[role="region"]')?.getAttribute("aria-label")).toBe("Afinidad por partido");
    fireEvent.click(screen.getByRole("button", { name: "Aviso sobre estos resultados" }));
    expect(warning.hidden).toBe(false);
    const methodology = screen.getByRole("link", { name: "Cómo se calcula la afinidad" });
    expect(methodology.getAttribute("href")).toBe("/metodologia");
    expect(methodology.getAttribute("target")).toBeNull();
    expect(screen.queryByRole("region", { name: "Hay un cuestionario más reciente" })).toBeNull();
    const cta = screen.getByRole("link", { name: "Haz tú el cuestionario" });
    expect(cta.getAttribute("href")).toBe("/elecciones/1/cuestionario");
    expect(cta.className).toBe("button-primary");
    expect(screen.getAllByText(/^Respuesta del enlace:/)).toHaveLength(6);
    expect(screen.getByText(NOTE).className).toBe("questionnaire__note");
    expect(screen.queryByRole("link", { name: "Volver al inicio" })).toBeNull();
  });

  test("logos are preloaded in Party order whatever the ranking, then shown in ranking order", async () => {
    const { srcs } = recordImageRequests();
    const fetch = routes({
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 6, logos: true })),
    });
    // Disagreeing with everything ranks Partido Dos first.
    renderAt("/resultados#v1-1-aaaaaa", fetch);
    await ready();
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(2)]);
    const names = Array.from(document.querySelectorAll(".ranking-row__name"), (el) => el.textContent);
    expect(names).toEqual(["Partido Dos", "Partido Uno"]);
    const ranking = Array.from(document.querySelectorAll(".ranking-row img"), (img) =>
      img.getAttribute("src"),
    );
    expect(ranking).toEqual([partyLogoUrl(2), partyLogoUrl(1)]);
    for (const summary of document.querySelectorAll(".position__summary")) {
      expect(summary.firstElementChild?.className).toBe("party-logo party-logo--breakdown");
    }
    expect(urls(fetch)).toEqual([VERSION_URL, ELECTION_URL]);
  });

  test("an invalid link preloads no logo", async () => {
    const { srcs } = recordImageRequests();
    renderAt("/resultados#v1-1-dddddf", sixStatements());
    await screen.findByText(INVALID);
    expect(srcs).toEqual([]);
  });

  test("Scenario 1: Haz tú el cuestionario opens the Questionnaire", async () => {
    const fetch = sixStatements();
    renderAt(LINK, fetch);
    await ready();
    fireEvent.click(screen.getByRole("link", { name: "Haz tú el cuestionario" }));
    expect(await screen.findByRole("radiogroup")).toBeTruthy();
    expect(currentLocation).toBe("/elecciones/1/cuestionario");
  });

  test("Scenario 2: a superseded version shows the notice above the unchanged result", async () => {
    const current = renderAt(LINK, sixStatements());
    await ready();
    const expected = { ranking: rankingTexts(), breakdown: breakdownTexts() };
    current.unmount();

    renderAt(LINK, sixStatements({ published_dataset_version_id: 2 }));
    await ready();
    const notice = screen.getByRole("region", { name: "Hay un cuestionario más reciente" });
    expect(notice.className).toBe("card shared-notice");
    expect(notice.getAttribute("role")).toBeNull();
    expect(within(notice).getByText(SUPERSEDED)).toBeTruthy();
    const link = within(notice).getByRole("link", { name: "Hacer el cuestionario actual" });
    expect(link.getAttribute("href")).toBe("/elecciones/1/cuestionario");
    // The notice comes before the ranking.
    const ranking = screen.getByRole("list", { name: "Afinidad con cada partido" });
    expect(notice.compareDocumentPosition(ranking) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Haz tú el cuestionario" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(rankingTexts()).toEqual(expected.ranking);
    expect(breakdownTexts()).toEqual(expected.breakdown);
  });

  test("Scenario 3: an archived Election with a newer version: notice without a link, no CTA", async () => {
    renderAt(LINK, sixStatements({ status: "archived", published_dataset_version_id: 2 }));
    await ready();
    const notice = screen.getByRole("region", { name: "Hay un cuestionario más reciente" });
    expect(within(notice).queryByRole("link")).toBeNull();
    expect(screen.queryByRole("link", { name: "Haz tú el cuestionario" })).toBeNull();
    expect(rankingTexts()).toHaveLength(2);
  });

  test("Scenario 3: no Published version: no notice, no CTA, result shown", async () => {
    renderAt(LINK, sixStatements({ published_dataset_version_id: null }));
    await ready();
    expect(screen.queryByRole("region", { name: "Hay un cuestionario más reciente" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Haz tú el cuestionario" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Hacer el cuestionario actual" })).toBeNull();
    expect(rankingTexts()).toHaveLength(2);
  });

  test("Scenario 3: an archived Election pinning its current version: no notice, no CTA", async () => {
    renderAt(LINK, sixStatements({ status: "archived" }));
    await ready();
    expect(screen.queryByRole("region", { name: "Hay un cuestionario más reciente" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Haz tú el cuestionario" })).toBeNull();
  });

  test("all skipped: counts, the no-scores sentence and the breakdown", async () => {
    renderAt("/resultados#v1-1-ssssSs", sixStatements());
    await ready();
    expect(screen.getByText("Muestra evaluada: 0/6 afirmaciones contestadas")).toBeTruthy();
    const summary = screen.getByRole("region", { name: "Muestra evaluada: 0/6 afirmaciones contestadas" });
    expect(within(summary).getByText("Se saltaron 6 afirmaciones.")).toBeTruthy();
    expect(summary.querySelector(".summary-donut")?.textContent).toBe("0\u00a0%");
    // No arc at 0 %, only the track.
    expect(summary.querySelector(".summary-donut__value")).toBeNull();
    expect(summary.querySelector(".summary-donut__track")).not.toBeNull();
    expect(screen.getByText("No se marcó ninguna afirmación como importante.")).toBeTruthy();
    expect(
      screen.getByText(
        "Las respuestas de este enlace no permiten calcular la afinidad: ninguna afirmación " +
          "respondida tiene la posición de algún partido.",
      ),
    ).toBeTruthy();
    expect(document.querySelector(".ranking")).toBeNull();
    expect(breakdownTexts()).toHaveLength(6);
  });

  test("several Important Statements use the plural sentence", async () => {
    renderAt("/resultados#v1-1-DDdddA", sixStatements());
    await ready();
    expect(screen.getByText("Se marcaron 3 afirmaciones como importantes.")).toBeTruthy();
  });

  test.each([LINK.split("#")[0]!, "/resultados#"])("Scenario 4: %s is missing, with no request", async (path) => {
    const fetch = sixStatements();
    renderAt(path, fetch);
    expect(await screen.findByText(MISSING)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" })).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });

  test.each(["#v1-1-dddddf", "#garbage", "#V1-1-a", `#v1-1-${"d".repeat(501)}`])(
    "Scenario 4: %s is invalid, with no request",
    async (hash) => {
      const fetch = sixStatements();
      renderAt(`/resultados${hash}`, fetch);
      expect(await screen.findByText(INVALID)).toBeTruthy();
      expect(document.querySelector(".ranking, .breakdown")).toBeNull();
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  test("Scenario 4: a 1025-character fragment is invalid, with no request", async () => {
    const fetch = sixStatements();
    const fragment = `v1-1-${"d".repeat(1020)}`;
    expect(fragment).toHaveLength(1025);
    renderAt(`/resultados#${fragment}`, fetch);
    expect(await screen.findByText(INVALID)).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("Scenario 4: #v2-1-a is unsupported, with no request", async () => {
    const fetch = sixStatements();
    renderAt("/resultados#v2-1-a", fetch);
    expect(await screen.findByText(UNSUPPORTED)).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });

  test.each(["#v1-1-ddddd", "#v1-1-ddddddd"])(
    "Scenario 4: a wrong letter count (%s) is invalid after exactly one request",
    async (hash) => {
      const fetch = sixStatements();
      renderAt(`/resultados${hash}`, fetch);
      expect(await screen.findByText(INVALID)).toBeTruthy();
      expect(urls(fetch)).toEqual([VERSION_URL]);
      expect(document.querySelector(".ranking, .breakdown")).toBeNull();
    },
  );

  test("Scenario 5: an unknown Dataset Version is not found after one request", async () => {
    const fetch = routes({ [VERSION_URL]: () => jsonResponse({ detail: "Not Found" }, 404) });
    renderAt(LINK, fetch);
    expect(await screen.findByText(NOT_FOUND)).toBeTruthy();
    expect(urls(fetch)).toEqual([VERSION_URL]);
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
  });

  test("Scenario 5: an unknown Election is not found", async () => {
    const fetch = routes({
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 6 })),
      [ELECTION_URL]: () => jsonResponse({ detail: "Not Found" }, 404),
    });
    renderAt(LINK, fetch);
    expect(await screen.findByText(NOT_FOUND)).toBeTruthy();
    expect(urls(fetch)).toEqual([VERSION_URL, ELECTION_URL]);
  });

  const failures: [string, Responder][] = [
    ["a rejected fetch", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a 500", () => textResponse(500)],
    ["an invalid body", () => jsonResponse({ id: "x" })],
  ];

  test.each(
    failures.flatMap(([name, fail]) => [
      [`${name} on the Dataset Version`, VERSION_URL, fail] as const,
      [`${name} on the Election`, ELECTION_URL, fail] as const,
    ]),
  )("Scenario 6: %s shows the alert; Reintentar repeats both requests", async (_name, url, fail) => {
    let failing = true;
    const good: Record<string, Responder> = {
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 6 })),
    };
    const fetch = vi.fn<FetchLike>(async (requested) => {
      if (failing && requested === url) return fail();
      return good[requested]!();
    });
    renderAt(LINK, fetch);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(ERROR)).toBeTruthy();
    expect(document.querySelector(".ranking, .breakdown")).toBeNull();
    const before = fetch.mock.calls.length;

    failing = false;
    fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(screen.getByRole("status").textContent).toBe("Cargando resultado…");
    await ready();
    expect(urls(fetch).slice(before)).toEqual([VERSION_URL, ELECTION_URL]);
    expect(rankingTexts()).toHaveLength(2);
  });

  test("Scenario 7: no request carries the answers; storage untouched; the URL keeps its fragment", async () => {
    const fetch = sixStatements();
    renderAt(LINK, fetch);
    await ready();
    for (const call of fetch.mock.calls) {
      expect(call[0]).not.toContain("dddddA");
      expect(call[0]).not.toContain("#");
      expect(JSON.stringify(call[1])).not.toContain("dddddA");
    }
    expect(currentLocation).toBe(LINK);
    expect(window.location.hash).toBe("");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  test("Scenario 8: h1 focused on mount, title set and restored; read-only page", async () => {
    document.title = "IdeologiApp";
    const fetch = sixStatements();
    const view = renderAt(LINK, fetch);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Resultado compartido");
    expect(document.activeElement).toBe(h1);
    expect(document.title).toBe(SHARED_RESULTS_TITLE);
    await ready();
    expect(document.activeElement).toBe(h1);
    expect(screen.queryByRole("button", { name: "Copiar enlace" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Comparte tu resultado" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Revisar mis respuestas" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Volver a la última afirmación" })).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    view.unmount();
    expect(document.title).toBe("IdeologiApp");
  });

  test("Scenario 8: the h1 and focus stay in every non-ready state", async () => {
    renderAt("/resultados#garbage", sixStatements());
    await screen.findByText(INVALID);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Resultado compartido");
    expect(document.activeElement).toBe(h1);
    expect(document.title).toBe(SHARED_RESULTS_TITLE);
  });

  test("a different fragment in the address bar opens that link (remount)", async () => {
    let navigate: ((to: string) => void) | undefined;
    function NavigateProbe() {
      navigate = useNavigate();
      return null;
    }
    const fetch = sixStatements();
    render(
      <MemoryRouter initialEntries={["/resultados"]}>
        <App api={createPublicApiClient({ fetch })} />
        <NavigateProbe />
      </MemoryRouter>,
    );
    expect(await screen.findByText(MISSING)).toBeTruthy();
    act(() => navigate!(LINK));
    await ready();
    expect(urls(fetch)).toEqual([VERSION_URL, ELECTION_URL]);
    act(() => navigate!("/resultados#garbage"));
    expect(await screen.findByText(INVALID)).toBeTruthy();
    expect(document.querySelector(".ranking")).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
