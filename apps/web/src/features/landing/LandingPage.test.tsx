import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike, type HttpResponseLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { electionJson, jsonResponse, textResponse } from "../../test/fetch-mocks";

const DISCLOSURE_TEXT =
  "Las afirmaciones y las posiciones de los partidos las ha generado automáticamente una " +
  "inteligencia artificial a partir de sus programas electorales, sin revisión humana, y pueden " +
  "contener errores. Cada posición se apoya en una cita literal del programa que podrás " +
  "consultar. Esta herramienta no es una recomendación de voto.";

const TRIAL_NOTICE =
  "Por ahora el cuestionario solo está disponible, a modo de prueba, para las elecciones " +
  "generales de 2023. Próximamente añadiremos las de 2026, cuando los partidos actualicen sus " +
  "programas electorales.";

function renderLanding(fetch: FetchLike) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
}

function fetchResolving(...responses: HttpResponseLike[]) {
  const fetch = vi.fn<FetchLike>();
  for (const response of responses) {
    fetch.mockResolvedValueOnce(response);
  }
  return fetch;
}

// Both cards render collapsed: the toggle sits in the h2, the panel is hidden.
function expectDisclosureAndMethodology() {
  for (const name of ["Contenido generado con IA", "Cómo funciona"]) {
    expect(screen.getByRole("heading", { level: 2, name })).toBeTruthy();
    expect(screen.getByRole("button", { name }).getAttribute("aria-expanded")).toBe("false");
  }
  const disclosure = screen.getByRole("region", { name: "Contenido generado con IA" });
  expect(within(disclosure).getByText(DISCLOSURE_TEXT).closest("[hidden]")).not.toBeNull();
  const methodology = screen.getByRole("region", { name: "Cómo funciona" });
  const link = within(methodology).getByRole("link", {
    name: "Lee la metodología completa",
    hidden: true,
  });
  expect(link.getAttribute("href")).toBe("/metodologia");
  expect(link.closest("[hidden]")).not.toBeNull();
}

function electionLinks() {
  const elections = screen.getByRole("region", { name: "Elecciones disponibles" });
  return within(elections).queryAllByRole("link");
}

describe("LandingPage", () => {
  test("Scenario 1: shows loading, then the published Election link, disclosure and methodology", async () => {
    let resolve: (response: HttpResponseLike) => void = () => {};
    const fetch = vi.fn<FetchLike>(
      () =>
        new Promise<HttpResponseLike>((r) => {
          resolve = r;
        }),
    );
    renderLanding(fetch);

    expect(screen.getByRole("status").textContent).toBe("Cargando elecciones…");
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("IdeologiApp");
    expect(h1.className).toBe("brand-title brand-title--on-brand");
    expect(h1.querySelector("img")?.getAttribute("alt")).toBe("");
    expect(h1.querySelector("img")?.getAttribute("src")).toMatch(/ideologiapp-bulb\.svg$/);
    expect(screen.getByText("Una forma sencilla de revisar los programas electorales").tagName).toBe("P");
    expectDisclosureAndMethodology();

    resolve(jsonResponse({ elections: [electionJson()] }));
    const link = await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023 Realizar cuestionario" });
    expect(link.getAttribute("href")).toBe("/elecciones/1/cuestionario");
    expect(within(link).getByText("23 de julio de 2023")).toBeTruthy();
    expect(within(link).getByText("Realizar cuestionario").parentElement?.className).toBe(
      "election-link__cta",
    );
    expect(screen.queryByRole("status")).toBeNull();
    expectDisclosureAndMethodology();
    expect(
      screen.getByText(
        "Responde a una serie de afirmaciones y descubre qué partidos se acercan más a tus " +
          "respuestas, según sus programas electorales.",
      ),
    ).toBeTruthy();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/elections", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("keeps the main content order: h1, intro, Elections, methodology, disclosure", async () => {
    renderLanding(fetchResolving(jsonResponse({ elections: [electionJson()] })));
    await screen.findByRole("link", { name: /Generales 2023/ });
    const main = screen.getByRole("main");
    const order = Array.from(main.querySelectorAll("h1, h2")).map((h) => h.textContent);
    expect(order).toEqual([
      "IdeologiApp",
      "Elecciones disponibles",
      "Cómo funciona",
      "Contenido generado con IA",
    ]);
    const header = main.firstElementChild!;
    expect(header.className).toBe("brand-header");
    expect(Array.from(header.children).map((child) => child.tagName)).toEqual(["H1", "P"]);
    expect(header.lastElementChild?.textContent).toBe("Una forma sencilla de revisar los programas electorales");
    expect(main.children[1]?.tagName).toBe("P");
  });

  test.each(["Contenido generado con IA", "Cómo funciona"])(
    "%s expands and collapses from its heading button",
    async (name) => {
      renderLanding(fetchResolving(jsonResponse({ elections: [electionJson()] })));
      await screen.findByRole("link", { name: /Generales 2023/ });
      const toggle = screen.getByRole("button", { name });
      const panel = document.getElementById(toggle.getAttribute("aria-controls")!)!;
      expect(toggle.parentElement?.tagName).toBe("H2");
      expect(screen.getByRole("region", { name }).contains(panel)).toBe(true);
      expect(panel.hidden).toBe(true);

      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
      expect(panel.hidden).toBe(false);

      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      expect(panel.hidden).toBe(true);
    },
  );

  test.each([
    ["a loaded list", jsonResponse({ elections: [electionJson()] })],
    ["an empty list", jsonResponse({ elections: [] })],
  ])("the trial notice follows the Elections title with %s", async (_label, response) => {
    renderLanding(fetchResolving(response));
    await screen.findByText(/Generales 2023|no hay elecciones/);
    const elections = screen.getByRole("region", { name: "Elecciones disponibles" });
    const card = within(elections).getByText(TRIAL_NOTICE).closest(".notice-card");
    expect(card).toBe(within(elections).getByRole("heading", { level: 2 }).nextElementSibling);
    expect(card?.className).toBe("notice-card notice-card--warning");
    const title = within(elections).getByRole("heading", { level: 3, name: "Versión de prueba" });
    expect(card?.contains(title)).toBe(true);
    expect(title.nextElementSibling?.textContent).toBe(TRIAL_NOTICE);
    expect(card?.querySelector(".notice-card__icon svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  test("the disclosure card shows the AI text once expanded", async () => {
    renderLanding(fetchResolving(jsonResponse({ elections: [electionJson()] })));
    await screen.findByRole("link", { name: /Generales 2023/ });
    fireEvent.click(screen.getByRole("button", { name: "Contenido generado con IA" }));
    const disclosure = screen.getByRole("region", { name: "Contenido generado con IA" });
    expect(within(disclosure).getByText(DISCLOSURE_TEXT).closest("[hidden]")).toBeNull();
  });

  test("links to the methodology page at the end of Cómo funciona", async () => {
    renderLanding(fetchResolving(jsonResponse({ elections: [electionJson()] })));
    await screen.findByRole("link", { name: /Generales 2023/ });
    expect(screen.getAllByRole("link")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Cómo funciona" }));
    const methodology = screen.getByRole("region", { name: "Cómo funciona" });
    const panel = document.getElementById(
      within(methodology).getByRole("button").getAttribute("aria-controls")!,
    )!;
    expect(panel.lastElementChild?.querySelector("a")?.textContent).toBe(
      "Lee la metodología completa",
    );
    const link = within(methodology).getByRole("link", { name: "Lee la metodología completa" });
    expect(link.getAttribute("href")).toBe("/metodologia");
    expect(link.className).toBe("text-link");
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  test("feedback-dialog: Danos tu opinión is last in main and sends origin landing", async () => {
    const fetch = vi.fn<FetchLike>(async (url) =>
      url === "/api/v1/feedback"
        ? jsonResponse({ status: "ok" }, 201)
        : jsonResponse({ elections: [electionJson()] }),
    );
    renderLanding(fetch);
    await screen.findByRole("link", { name: /Generales 2023/ });
    const main = screen.getByRole("main");
    const feedback = screen.getByRole("button", { name: "Danos tu opinión" });
    expect(feedback.className).toBe("button-secondary");
    expect(feedback.getAttribute("aria-haspopup")).toBe("dialog");
    expect(main.lastElementChild).toBe(feedback.parentElement);
    expect(feedback.parentElement?.className).toBe("feedback-entry");
    const disclosure = screen.getByRole("region", { name: "Contenido generado con IA" });
    expect(disclosure.nextElementSibling).toBe(feedback.parentElement);

    fireEvent.click(feedback);
    const dialog = screen.getByRole("dialog", { name: "Ayúdanos a mejorar" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Tu opinión" }), {
      target: { value: "Muy útil" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Enviar" }));
    expect(await within(dialog).findByText("¡Gracias por tu opinión!")).toBeTruthy();
    const post = fetch.mock.calls.find(([url]) => url === "/api/v1/feedback")!;
    expect(post[1]?.method).toBe("POST");
    expect(JSON.parse(String(post[1]?.body))).toEqual({ message: "Muy útil", origin: "landing" });
  });

  test("Scenario 4: an empty list shows the empty message and no link", async () => {
    renderLanding(fetchResolving(jsonResponse({ elections: [] })));
    expect(
      await screen.findByText(
        "Ahora mismo no hay elecciones disponibles. Vuelve a consultarlo más adelante.",
      ),
    ).toBeTruthy();
    expect(electionLinks()).toHaveLength(0);
    expect(screen.queryByRole("list")).toBeNull();
    expectDisclosureAndMethodology();
  });

  test.each([
    ["a 500 response", () => vi.fn<FetchLike>().mockResolvedValueOnce(textResponse(500))],
    [
      "a rejected fetch",
      () => vi.fn<FetchLike>().mockRejectedValueOnce(new TypeError("Failed to fetch")),
    ],
    [
      "an invalid body",
      () =>
        vi
          .fn<FetchLike>()
          .mockResolvedValueOnce(jsonResponse({ elections: [electionJson({ date: "23/07/2023" })] })),
    ],
  ])("Scenario 5: %s shows the alert, and Reintentar loads the list", async (_label, makeFetch) => {
    const fetch = makeFetch();
    let resolve: (response: HttpResponseLike) => void = () => {};
    fetch.mockImplementationOnce(
      () =>
        new Promise<HttpResponseLike>((r) => {
          resolve = r;
        }),
    );
    renderLanding(fetch);

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(
      "No se han podido cargar las elecciones. Comprueba tu conexión e inténtalo de nuevo.",
    )).toBeTruthy();
    expect(electionLinks()).toHaveLength(0);
    expectDisclosureAndMethodology();

    fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(screen.getByRole("status").textContent).toBe("Cargando elecciones…");
    expect(screen.queryByRole("alert")).toBeNull();

    resolve(jsonResponse({ elections: [electionJson()] }));
    expect(
      await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023 Realizar cuestionario" }),
    ).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  test("Scenario 6: several Elections keep the API order and identical styling", async () => {
    renderLanding(
      fetchResolving(
        jsonResponse({
          elections: [
            electionJson({ id: 3, date: "2027-07-01", name: "Generales 2027", published_dataset_version_id: 2 }),
            electionJson(),
          ],
        }),
      ),
    );
    await screen.findByRole("link", { name: /Generales 2027/ });
    const links = electionLinks();
    expect(links.map((link) => link.textContent)).toEqual([
      "Generales 2027 1 de julio de 2027 Realizar cuestionario",
      "Generales 2023 23 de julio de 2023 Realizar cuestionario",
    ]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/elecciones/3/cuestionario",
      "/elecciones/1/cuestionario",
    ]);
    expect(links[0]?.className).toBe("election-link");
    expect(links[1]?.className).toBe(links[0]?.className);
    expect(links.every((link) => link.getAttribute("style") === null)).toBe(true);
  });
});
