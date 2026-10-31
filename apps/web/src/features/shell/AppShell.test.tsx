import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { electionJson, jsonResponse } from "../../test/fetch-mocks";

function renderAt(path: string) {
  const fetch = vi.fn<FetchLike>(async () => jsonResponse({ elections: [electionJson()] }));
  render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
  return fetch;
}

function sidebar() {
  return screen.getByRole("complementary", { name: "Menú principal" });
}

describe("AppShell", () => {
  test.each([
    ["/", "Elecciones"],
    ["/metodologia", "Cómo funciona"],
    ["/transparencia", "Transparencia IA"],
  ])("at %s the sidebar marks %s as the current section", async (path, label) => {
    renderAt(path);
    const nav = within(sidebar()).getByRole("navigation", { name: "Secciones" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Elecciones", "/"],
      ["Cómo funciona", "/metodologia"],
      ["Transparencia IA", "/transparencia"],
    ]);
    const current = links.filter((link) => link.getAttribute("aria-current") === "page");
    expect(current.map((link) => link.textContent)).toEqual([label]);
    expect(screen.getByRole("banner").textContent).toBe(`IdeologiApp/${label}`);
    await screen.findAllByRole("heading", { level: 1 });
  });

  test("the shared result and unknown paths are in the shell too", () => {
    renderAt("/no-existe");
    expect(sidebar()).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Página no encontrada" })).toBeTruthy();
    expect(screen.getByRole("banner").textContent).toBe("IdeologiApp");
  });

  test("the menu button opens the drawer, Escape closes it and focus returns", async () => {
    renderAt("/metodologia");
    const menu = screen.getByRole("button", { name: "Abrir menú" });
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(menu.getAttribute("aria-controls")).toBe(sidebar().id);

    fireEvent.click(menu);
    expect(menu.getAttribute("aria-expanded")).toBe("true");
    const canvas = screen.getByRole("main").closest(".app-shell__canvas") as HTMLElement;
    expect(canvas.hasAttribute("inert")).toBe(true);
    expect(sidebar().contains(document.activeElement)).toBe(true);

    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(canvas.hasAttribute("inert")).toBe(false);
    expect(document.activeElement).toBe(menu);
  });

  test("Cerrar menú closes the drawer, and following a link closes it too", async () => {
    renderAt("/metodologia");
    const menu = screen.getByRole("button", { name: "Abrir menú" });
    fireEvent.click(menu);
    fireEvent.click(within(sidebar()).getByRole("button", { name: "Cerrar menú" }));
    expect(menu.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(menu);
    fireEvent.click(within(sidebar()).getByRole("link", { name: "Transparencia IA" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Transparencia IA" })).toBeTruthy();
    expect(menu.getAttribute("aria-expanded")).toBe("false");
  });

  test("tapping the current section closes the drawer", () => {
    renderAt("/metodologia");
    const menu = screen.getByRole("button", { name: "Abrir menú" });
    fireEvent.click(menu);
    fireEvent.click(within(sidebar()).getByRole("link", { name: "Cómo funciona" }));
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    const canvas = screen.getByRole("main").closest(".app-shell__canvas") as HTMLElement;
    expect(canvas.hasAttribute("inert")).toBe(false);
    expect(document.activeElement).toBe(menu);
  });

  test.each(["Elecciones", "IdeologiApp"])(
    "the drawer link %s goes home and focuses the Landing h1",
    async (name) => {
      renderAt("/metodologia");
      fireEvent.click(screen.getByRole("button", { name: "Abrir menú" }));
      fireEvent.click(within(sidebar()).getByRole("link", { name }));
      const h1 = await screen.findByRole("heading", { level: 1, name: "IdeologiApp" });
      expect(document.activeElement).toBe(h1);
    },
  );

  test("the Questionnaire has no sidebar", () => {
    renderAt("/elecciones/1/cuestionario");
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.queryByRole("button", { name: "Abrir menú" })).toBeNull();
  });
});
