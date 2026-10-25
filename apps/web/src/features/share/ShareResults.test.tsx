import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, test, vi } from "vitest";

import {
  createPublicApiClient,
  decodeShareLink,
  type FetchLike,
  type HttpResponseLike,
} from "@ideology-app/core";

import { App } from "../../app/App";
import { datasetVersionJson, electionJson, jsonResponse } from "../../test/fetch-mocks";

const FALLBACK = "No se ha podido copiar el enlace automáticamente. Cópialo desde este campo:";
const NOTE =
  "No se guarda nada en ningún servidor: tus respuestas van dentro del propio enlace, tras el " +
  "símbolo «#», y el navegador no envía esa parte de la dirección. Cualquiera que tenga el " +
  "enlace podrá ver tus respuestas.";

function routes(table: Record<string, () => HttpResponseLike>) {
  return vi.fn<FetchLike>(async (url) => {
    const respond = table[url];
    if (respond === undefined) {
      throw new Error(`unexpected request ${url}`);
    }
    return respond();
  });
}

function sixStatementFetch() {
  return routes({
    "/api/v1/elections/1": () => jsonResponse(electionJson()),
    "/api/v1/dataset-versions/1": () => jsonResponse(datasetVersionJson({ statements: 6 })),
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

function button(name: string) {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

type Step = { readonly rate?: string; readonly important?: boolean; readonly skip?: boolean };

/** Opens the six-Statement Questionnaire and answers it step by step. */
async function finish(steps: readonly Step[], fetch: FetchLike = sixStatementFetch()) {
  renderAt("/elecciones/1/cuestionario", fetch);
  await screen.findByRole("radiogroup");
  for (const step of steps) {
    if (step.important) fireEvent.click(button("Importante para mí"));
    if (step.skip) {
      fireEvent.click(button("Saltar esta afirmación"));
    } else {
      fireEvent.click(screen.getByRole("radio", { name: step.rate ?? "De acuerdo" }));
      fireEvent.click(button("Siguiente"));
    }
  }
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Tus resultados");
  return fetch;
}

const SCENARIO_1: readonly Step[] = [
  {},
  {},
  {},
  {},
  {},
  { rate: "Muy en desacuerdo", important: true },
];

function defineClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", { value, configurable: true });
}

function shareSection() {
  return screen.getByRole("region", { name: "Comparte tu resultado" });
}

afterEach(() => {
  // vi.unstubAllGlobals does not restore a defined navigator property.
  delete (navigator as { clipboard?: unknown }).clipboard;
  currentLocation = "";
});

describe("ShareResults", () => {
  test("Scenario 1: Copiar enlace writes the Share Link to the clipboard; no request, no field", async () => {
    const writeText = vi.fn(async (_text: string) => undefined);
    defineClipboard({ writeText });
    const fetch = await finish(SCENARIO_1);
    const section = shareSection();
    const status = within(section).getByRole("status");
    expect(status.textContent).toBe("");

    const copyButton = within(section).getByRole("button", { name: "Copiar enlace" });
    copyButton.focus(); // fireEvent.click does not move focus as a real click does
    fireEvent.click(copyButton);
    expect(await within(section).findByText("Enlace copiado.")).toBe(status);

    const url = `${window.location.origin}/resultados#v1-1-dddddA`;
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(url);
    expect(url).not.toContain("?");
    expect(url.split("#")).toHaveLength(2);
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(document.activeElement).toBe(copyButton);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  test("the share title and Copiar enlace carry decorative icons; the names are unchanged", async () => {
    await finish(SCENARIO_1);
    const section = shareSection();
    const title = within(section).getByRole("heading", { level: 3, name: "Comparte tu resultado" });
    const copyButton = within(section).getByRole("button", { name: "Copiar enlace" });
    for (const element of [title, copyButton]) {
      const icons = element.querySelectorAll("svg");
      expect(icons).toHaveLength(1);
      expect(icons[0]!.getAttribute("aria-hidden")).toBe("true");
    }
    const notice = screen
      .getByText(/^Esto no es una recomendación de voto/)
      .closest(".notice-card");
    expect(notice?.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  test("Scenario 2: a skip and a flagged skip are encoded with their flags", async () => {
    const writeText = vi.fn(async (_text: string) => undefined);
    defineClipboard({ writeText });
    await finish([{}, { important: true, skip: true }, {}, {}, {}, { skip: true }]);
    fireEvent.click(button("Copiar enlace"));
    await screen.findByText("Enlace copiado.");
    const url = writeText.mock.calls[0]![0];
    expect(url).toBe(`${window.location.origin}/resultados#v1-1-dSddds`);
    expect(decodeShareLink(url.split("#")[1]!).entries).toEqual([
      { value: 1, important: false },
      { value: "skip", important: true },
      { value: 1, important: false },
      { value: 1, important: false },
      { value: 1, important: false },
      { value: "skip", important: false },
    ]);
  });

  async function expectFallback() {
    const section = shareSection();
    fireEvent.click(within(section).getByRole("button", { name: "Copiar enlace" }));
    await within(section).findByText(FALLBACK);
    const field = within(section).getByRole("textbox", {
      name: "Enlace para compartir",
    }) as HTMLInputElement;
    const url = `${window.location.origin}/resultados#v1-1-dddddA`;
    expect(field.value).toBe(url);
    expect(field.readOnly).toBe(true);
    expect(field.className).toBe("share__field");
    // Focus is moved in a passive effect, which can run just after the text appears.
    await vi.waitFor(() => expect(document.activeElement).toBe(field));
    expect(field.selectionStart).toBe(0);
    expect(field.selectionEnd).toBe(url.length);
    return field;
  }

  test("Scenario 3: without navigator.clipboard the link shows in a focused, selected field", async () => {
    defineClipboard(undefined);
    const fetch = await finish(SCENARIO_1);
    const field = await expectFallback();

    // A second click focuses and selects the field again.
    field.setSelectionRange(0, 0);
    button("Copiar enlace").focus();
    fireEvent.click(button("Copiar enlace"));
    await vi.waitFor(() => expect(document.activeElement).toBe(field));
    expect(field.selectionEnd).toBe(field.value.length);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  test("Scenario 3: a clipboard without writeText falls back to the field", async () => {
    defineClipboard({});
    await finish(SCENARIO_1);
    await expectFallback();
  });

  test("Scenario 3: writeText rejecting with NotAllowedError falls back to the field", async () => {
    const writeText = vi.fn(async (_text: string) => {
      throw new DOMException("Write permission denied.", "NotAllowedError");
    });
    defineClipboard({ writeText });
    await finish(SCENARIO_1);
    await expectFallback();
    expect(writeText).toHaveBeenCalledTimes(1);
  });

  test("Scenario 3: writeText throwing synchronously falls back to the field", async () => {
    defineClipboard({
      writeText: () => {
        throw new TypeError("not allowed");
      },
    });
    await finish(SCENARIO_1);
    await expectFallback();
  });

  test("Scenario 4: when every Statement is skipped there is nothing to share", async () => {
    await finish(Array.from({ length: 6 }, () => ({ skip: true })));
    expect(screen.getByText(/Todavía no se puede calcular tu afinidad/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Comparte tu resultado" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copiar enlace" })).toBeNull();
  });

  test("Scenario 5: the note shows, and the URL, history, storage and cookies are unchanged", async () => {
    defineClipboard({ writeText: async () => undefined });
    await finish(SCENARIO_1);
    const section = shareSection();
    expect(section.className).toBe("share");
    expect(within(section).getByText(NOTE).className).toBe("questionnaire__note");
    expect(within(section).getByText("Copia un enlace que lleva tus respuestas para compartir este resultado.")).toBeTruthy();

    const before = {
      location: currentLocation,
      href: window.location.href,
      historyLength: window.history.length,
    };
    fireEvent.click(button("Copiar enlace"));
    await screen.findByText("Enlace copiado.");
    expect(currentLocation).toBe("/elecciones/1/cuestionario");
    expect(currentLocation).toBe(before.location);
    expect(window.location.href).toBe(before.href);
    expect(window.location.hash).toBe("");
    expect(window.history.length).toBe(before.historyLength);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  test("Scenario 6: the copied link opens the same result at /resultados", async () => {
    const writeText = vi.fn(async (_text: string) => undefined);
    defineClipboard({ writeText });
    await finish(SCENARIO_1);
    const ranking = Array.from(document.querySelectorAll(".ranking-row")).map((li) => li.textContent);
    fireEvent.click(button("Copiar enlace"));
    await screen.findByText("Enlace copiado.");
    const url = writeText.mock.calls[0]![0];
    cleanup();

    const fetch = sixStatementFetch();
    renderAt(url.slice(window.location.origin.length), fetch);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Resultado compartido");
    expect(document.activeElement).toBe(h1);
    await screen.findByRole("heading", { level: 2, name: "Afinidad con cada partido" });
    expect(Array.from(document.querySelectorAll(".ranking-row")).map((li) => li.textContent)).toEqual(
      ranking,
    );
    expect(currentLocation).toBe("/resultados#v1-1-dddddA");
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/dataset-versions/1",
      "/api/v1/elections/1",
    ]);
    expect(screen.queryByText("Página no encontrada")).toBeNull();
  });
});
