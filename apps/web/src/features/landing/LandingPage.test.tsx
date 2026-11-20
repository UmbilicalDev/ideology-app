import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike, type HttpResponseLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { DONATION_PATH, apiPaths, electionJson, jsonResponse, textResponse } from "../../test/fetch-mocks";

const FOOTER_TEXT =
  "IdeologiApp no es una recomendación de voto. Las afirmaciones y las posiciones las genera " +
  "una inteligencia artificial y pueden contener errores.";

// The App-level donation request (donate-buymeacoffee) is answered here by
// URL, so the queued `mock*Once` responses all go to the Landing's requests.
function renderLanding(fetch: FetchLike) {
  const routed: FetchLike = (url, init) =>
    url === DONATION_PATH ? Promise.resolve(jsonResponse({ url: null })) : fetch(url, init);
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <App api={createPublicApiClient({ fetch: routed })} />
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

// The AI disclosure is no longer a Landing card (web-redesign): the shell
// footer states it on every page and /transparencia explains it.
function expectDisclosureAndMethodology() {
  expect(screen.queryByRole("region", { name: "Contenido generado con IA" })).toBeNull();
  const footer = screen.getByRole("contentinfo");
  expect(footer.querySelector("p")?.textContent).toBe(FOOTER_TEXT);
  // legal-privacy-page: the footer's second line links to the legal page.
  expect(footer.textContent).toBe(`${FOOTER_TEXT}Aviso legal y privacidad`);
  // No section title and no methodology link (it is in the sidebar): the
  // carousel region carries the name.
  expect(screen.queryByRole("heading", { name: "Cómo funciona" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Lee la metodología completa" })).toBeNull();
  expect(screen.getByRole("region", { name: "Cómo funciona" }).getAttribute("aria-roledescription")).toBe(
    "carrusel",
  );
}

function electionLinks() {
  const elections = screen.getByRole("region", { name: "Elecciones" });
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
    expect(h1.querySelector("img")?.getAttribute("alt")).toBe("");
    const main = screen.getByRole("main");
    expect(within(main).getByText("Comparador de programas electorales").tagName).toBe("P");
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
    const lead = document.querySelector("ul.landing__lead");
    expect(lead).not.toBeNull();
    expect(within(lead as HTMLElement).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Responde al cuestionario.",
      "Descubre con quién concuerdan tus respuestas.",
      "Comprueba las citas sobre las afirmaciones en los programas.",
    ]);

    expect(apiPaths(fetch)).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/elections", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("keeps the main content order: h1, intro, Elections, carousel", async () => {
    renderLanding(fetchResolving(jsonResponse({ elections: [electionJson()] })));
    await screen.findByRole("link", { name: /Generales 2023/ });
    const main = screen.getByRole("main");
    const order = Array.from(main.querySelectorAll("h1, h2")).map((h) => h.textContent);
    // The carousel has no section title: its pages carry the h2s (the
    // hidden ones are aria-hidden, see HowItWorksCarousel.test.tsx).
    // No Elections heading (ui-2026-focus-tweaks): the region has a name.
    expect(order).toEqual([
      "IdeologiApp",
      "Responde a las afirmaciones",
      "Revisa tus resultados",
      "Comprueba de dónde vienen los resultados",
    ]);
    expect(main.firstElementChild?.tagName).toBe("H1");
    const elections = screen.getByRole("region", { name: "Elecciones" });
    expect(elections.tagName).toBe("SECTION");
    expect(elections.getAttribute("aria-label")).toBe("Elecciones");
    expect(elections.querySelector("h2, .section-head")).toBeNull();
    expect(screen.queryByText(/disponibles/)).toBeNull();
    expect(main.children[1]?.tagName).toBe("P");
    // The carousel ends the page: no checks/privacy sentence after it.
    expect(main.lastElementChild).toBe(screen.getByRole("region", { name: "Cómo funciona" }));
    expect(within(main).queryByText(/Tus respuestas se quedan en tu navegador/)).toBeNull();
  });

  test("the only links in main are the Elections (methodology is in the sidebar)", async () => {
    renderLanding(fetchResolving(jsonResponse({ elections: [electionJson()] })));
    await screen.findByRole("link", { name: /Generales 2023/ });
    const main = screen.getByRole("main");
    expect(
      within(main)
        .getAllByRole("link")
        .map((l) => l.getAttribute("href")),
    ).toEqual(["/elecciones/1/cuestionario"]);
  });

  test("the grid lists only the API's Elections (no fixed upcoming card)", async () => {
    renderLanding(fetchResolving(jsonResponse({ elections: [electionJson()] })));
    await screen.findByRole("link", { name: /Generales 2023/ });
    const items = within(screen.getByRole("region", { name: "Elecciones" })).getAllByRole(
      "listitem",
    );
    expect(items).toHaveLength(1);
    // No Disponible / Próximamente chips (user decision 2026-11-03).
    expect(document.querySelector(".status-badge")).toBeNull();
    expect(within(items[0]!).queryByText("Disponible")).toBeNull();
    expect(screen.queryByText("Próximamente")).toBeNull();
    expect(screen.queryByText(/^Pronto añadiremos/)).toBeNull();
  });

  test("an Election without a published Dataset Version is marked En preparación", async () => {
    renderLanding(
      fetchResolving(
        jsonResponse({ elections: [electionJson({ published_dataset_version_id: null })] }),
      ),
    );
    await screen.findByRole("link", { name: /Generales 2023/ });
    expect(screen.getByText("En preparación").className).toBe("status-badge status-badge--muted");
    expect(screen.queryByText("Disponible")).toBeNull();
  });

  test("feedback-dialog: Danos tu opinión is in the sidebar footer and sends origin landing", async () => {
    const fetch = vi.fn<FetchLike>(async (url) =>
      url === "/api/v1/feedback"
        ? jsonResponse({ status: "ok" }, 201)
        : jsonResponse({ elections: [electionJson()] }),
    );
    renderLanding(fetch);
    await screen.findByRole("link", { name: /Generales 2023/ });
    const sidebar = screen.getByRole("complementary", { name: "Menú principal" });
    const feedback = within(sidebar).getByRole("button", { name: "Danos tu opinión" });
    expect(feedback.className).toBe("button-secondary");
    expect(feedback.getAttribute("aria-haspopup")).toBe("dialog");
    expect(feedback.parentElement?.className).toBe("sidebar__footer");
    expect(within(screen.getByRole("main")).queryByRole("button", { name: "Danos tu opinión" })).toBeNull();

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
    // The grid is empty: no fixed upcoming card any more.
    const elections = screen.getByRole("region", { name: "Elecciones" });
    expect(within(elections).queryAllByRole("listitem")).toHaveLength(0);
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
    expect(apiPaths(fetch)).toHaveLength(2);
  });

  test("ui-2026-focus-tweaks: only the most recent Election is listed, whatever the API order", async () => {
    renderLanding(
      fetchResolving(
        jsonResponse({
          elections: [
            electionJson(),
            electionJson({ id: 3, date: "2027-07-01", name: "Generales 2027", published_dataset_version_id: 4 }),
            electionJson({ id: 2, date: "2026-11-29", name: "Generales 2026", published_dataset_version_id: 2 }),
          ],
        }),
      ),
    );
    await screen.findByRole("link", { name: /Generales 2027/ });
    const links = electionLinks();
    expect(links.map((link) => link.textContent)).toEqual([
      "Generales 2027 1 de julio de 2027 Realizar cuestionario",
    ]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/elecciones/3/cuestionario"]);
    expect(links[0]?.className).toBe("election-link");
    expect(links[0]?.getAttribute("style")).toBeNull();
    expect(within(screen.getByRole("region", { name: "Elecciones" })).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText(/Generales 2023|Generales 2026/)).toBeNull();
    expect(screen.queryByText(/disponibles/)).toBeNull();
  });

  test("ui-2026-focus-tweaks: the most recent Election keeps En preparación when unpublished", async () => {
    renderLanding(
      fetchResolving(
        jsonResponse({
          elections: [
            electionJson(),
            electionJson({ id: 2, date: "2026-11-29", name: "Generales 2026", published_dataset_version_id: null }),
          ],
        }),
      ),
    );
    const link = await screen.findByRole("link", { name: /Generales 2026/ });
    expect(link.getAttribute("href")).toBe("/elecciones/2/cuestionario");
    expect(screen.getByText("En preparación").className).toBe("status-badge status-badge--muted");
    expect(electionLinks()).toHaveLength(1);
  });
});
