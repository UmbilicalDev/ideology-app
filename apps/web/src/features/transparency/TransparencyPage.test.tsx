import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { TRANSPARENCY_PATH } from "../paths";

function renderTransparency() {
  const fetch = vi.fn<FetchLike>();
  render(
    <MemoryRouter initialEntries={[TRANSPARENCY_PATH]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
  return fetch;
}

describe("TransparencyPage", () => {
  test("renders at /transparencia with the h1 focused and its title, without requests", () => {
    const fetch = renderTransparency();
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Transparencia IA");
    expect(document.activeElement).toBe(h1);
    expect(document.title).toBe("Transparencia IA · IdeologiApp");
    expect(fetch).not.toHaveBeenCalled();
  });

  test("has the four sections in order and states the limits", () => {
    renderTransparency();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Qué genera la IA",
      "Qué se comprueba",
      "Tus respuestas",
      "Lo que no puede garantizar",
    ]);
    const limits = screen.getByRole("region", { name: "Lo que no puede garantizar" });
    const items = within(limits).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toContain("Esta herramienta no es una recomendación de voto.");
    expect(items.some((text) => text?.includes("sin revisión humana"))).toBe(true);
  });

  test("links to the full methodology and home", () => {
    renderTransparency();
    const main = screen.getByRole("main");
    expect(
      within(main)
        .getAllByRole("link")
        .map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Lee la metodología completa", "/metodologia"],
      ["Volver al inicio", "/"],
    ]);
  });
});
