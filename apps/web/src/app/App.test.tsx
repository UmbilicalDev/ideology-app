import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { datasetVersionJson, electionJson, jsonResponse } from "../test/fetch-mocks";
import { App } from "./App";

function renderAt(path: string, fetch: FetchLike) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
}

describe("App routes", () => {
  test("choosing an Election opens the Questionnaire, and Volver al inicio returns from the end", async () => {
    const fetch = vi.fn<FetchLike>(async (url) => {
      if (url === "/api/v1/elections") return jsonResponse({ elections: [electionJson()] });
      if (url === "/api/v1/elections/1") return jsonResponse(electionJson());
      if (url === "/api/v1/dataset-versions/1") return jsonResponse(datasetVersionJson({ statements: 1 }));
      throw new Error(`unexpected request ${url}`);
    });
    renderAt("/", fetch);

    fireEvent.click(await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023 Realizar cuestionario" }));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("IdeologiApp");
    expect(
      await screen.findByRole("radiogroup", { name: "Afirmación de prueba 1" }),
    ).toBeTruthy();
    expect(screen.getByText("Afirmación 1 de 1")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Saltar esta afirmación" }));
    expect(screen.getByText("Muestra evaluada: 0/1 afirmaciones contestadas")).toBeTruthy();
    const homeLinks = screen.getAllByRole("link", { name: "Volver al inicio" });
    expect(homeLinks).toHaveLength(2);
    fireEvent.click(homeLinks[1]!);
    expect(
      await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023 Realizar cuestionario" }),
    ).toBeTruthy();
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/elections",
      "/api/v1/elections/1",
      "/api/v1/dataset-versions/1",
      "/api/v1/elections",
    ]);
  });

  test("the largest valid id loads that Election", async () => {
    const fetch = vi.fn<FetchLike>(async () => jsonResponse({ error: {} }, 404));
    renderAt("/elecciones/2147483647/cuestionario", fetch);
    expect(await screen.findByText("Página no encontrada")).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith("/api/v1/elections/2147483647", expect.anything());
  });

  test.each([
    "/elecciones/abc/cuestionario",
    "/elecciones/0/cuestionario",
    "/elecciones/01/cuestionario",
    "/elecciones/2147483648/cuestionario",
    "/nada",
    "/metodologia/x",
  ])("%s renders Página no encontrada without an API request", (path) => {
    const fetch = vi.fn<FetchLike>();
    renderAt(path, fetch);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Página no encontrada");
    expect(screen.getByText("Esta dirección no corresponde a ninguna página.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
    expect(fetch).not.toHaveBeenCalled();
  });

  test("the Landing links to the methodology page, and Volver al inicio restores the title", async () => {
    document.title = "IdeologiApp";
    const fetch = vi.fn<FetchLike>(async () => jsonResponse({ elections: [electionJson()] }));
    renderAt("/", fetch);
    await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023 Realizar cuestionario" });

    fireEvent.click(screen.getByRole("link", { name: "Lee la metodología completa" }));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Metodología");
    expect(document.activeElement).toBe(h1);
    expect(document.title).toBe("Metodología · IdeologiApp");
    expect(fetch).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("link", { name: "Volver al inicio" }));
    expect(
      await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023 Realizar cuestionario" }),
    ).toBeTruthy();
    expect(document.title).toBe("IdeologiApp");
  });

  test("the methodology deep link renders without an API request", () => {
    const fetch = vi.fn<FetchLike>();
    renderAt("/metodologia", fetch);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Metodología");
    expect(fetch).not.toHaveBeenCalled();
  });

  test("the /resultados deep link opens the Share Link with two id-only requests", async () => {
    const fetch = vi.fn<FetchLike>(async (url) => {
      if (url === "/api/v1/dataset-versions/1") return jsonResponse(datasetVersionJson({ statements: 6 }));
      if (url === "/api/v1/elections/1") return jsonResponse(electionJson());
      throw new Error(`unexpected request ${url}`);
    });
    renderAt("/resultados#v1-1-dddddA", fetch);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Resultado compartido");
    expect(
      await screen.findByRole("heading", { level: 2, name: "Afinidad con cada partido" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/dataset-versions/1",
      "/api/v1/elections/1",
    ]);
  });

  test("global fetch is blocked in web tests", () => {
    expect(() => fetch("/api/v1/elections")).toThrow("network access is blocked in web tests");
  });
});
