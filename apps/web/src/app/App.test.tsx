import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { electionJson, jsonResponse } from "../test/fetch-mocks";
import { App } from "./App";

function renderAt(path: string, fetch: FetchLike) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
}

describe("App routes", () => {
  test("Scenario 2: choosing an Election shows the placeholder, and Volver al inicio returns", async () => {
    const fetch = vi.fn<FetchLike>(async () => jsonResponse({ elections: [electionJson()] }));
    renderAt("/", fetch);

    fireEvent.click(await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023" }));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Cuestionario");
    expect(
      screen.getByText("El cuestionario de estas elecciones estará disponible muy pronto."),
    ).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("link", { name: "Volver al inicio" }));
    expect(
      await screen.findByRole("link", { name: "Generales 2023 23 de julio de 2023" }),
    ).toBeTruthy();
  });

  test("Scenario 3: the Questionnaire deep link renders without an API request", () => {
    const fetch = vi.fn<FetchLike>();
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Cuestionario");
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
    expect(fetch).not.toHaveBeenCalled();
  });

  test("Scenario 3: the largest valid id renders the placeholder", () => {
    renderAt("/elecciones/2147483647/cuestionario", vi.fn<FetchLike>());
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Cuestionario");
  });

  test.each([
    "/elecciones/abc/cuestionario",
    "/elecciones/0/cuestionario",
    "/elecciones/01/cuestionario",
    "/elecciones/2147483648/cuestionario",
    "/nada",
  ])("Scenario 3: %s renders Página no encontrada without an API request", (path) => {
    const fetch = vi.fn<FetchLike>();
    renderAt(path, fetch);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Página no encontrada");
    expect(screen.getByText("Esta dirección no corresponde a ninguna página.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
    expect(fetch).not.toHaveBeenCalled();
  });

  test("global fetch is blocked in web tests", () => {
    expect(() => fetch("/api/v1/elections")).toThrow("network access is blocked in web tests");
  });
});
