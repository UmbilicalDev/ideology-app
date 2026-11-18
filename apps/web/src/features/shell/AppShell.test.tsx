import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { electionJson, jsonResponse } from "../../test/fetch-mocks";

function renderAt(path: string) {
  const fetch = vi.fn<FetchLike>(async (url) =>
    url === "/api/v1/legal-notice"
      ? jsonResponse({ holders: [], contact_email: null, address: null })
      : jsonResponse({ elections: [electionJson()] }),
  );
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
    // Ir al inicio shows only on the shared result.
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
    expect(screen.getByRole("link", { name: "IdeologiApp, ir al inicio" }).getAttribute("href")).toBe("/");
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

  // legal-privacy-page: the legal page is linked from the sidebar footer and the shell footer.
  test.each(["/", "/metodologia", "/transparencia", "/no-existe", "/legal"])(
    "at %s the sidebar and the footer link to /legal",
    async (path) => {
      renderAt(path);
      const sidebarLink = within(sidebar()).getByRole("link", { name: "Aviso legal y privacidad" });
      expect(sidebarLink.getAttribute("href")).toBe("/legal");
      expect(sidebarLink.parentElement?.className).toBe("sidebar__footer");
      expect(sidebarLink.className).toBe("sidebar__legal-link");
      const footerLink = within(screen.getByRole("contentinfo")).getByRole("link", {
        name: "Aviso legal y privacidad",
      });
      expect(footerLink.getAttribute("href")).toBe("/legal");
      expect(footerLink.className).toBe("text-link");
      // Not a section of the nav: never marked as the current one.
      const nav = within(sidebar()).getByRole("navigation", { name: "Secciones" });
      expect(within(nav).queryByRole("link", { name: "Aviso legal y privacidad" })).toBeNull();
      await screen.findAllByRole("heading", { level: 1 });
    },
  );

  test("the footer link opens /legal with the crumb Aviso legal", async () => {
    renderAt("/transparencia");
    fireEvent.click(
      within(screen.getByRole("contentinfo")).getByRole("link", { name: "Aviso legal y privacidad" }),
    );
    const h1 = await screen.findByRole("heading", { level: 1, name: "Aviso legal y privacidad" });
    expect(document.activeElement).toBe(h1);
    expect(screen.getByRole("banner").textContent).toBe("IdeologiApp/Aviso legal");
    await screen.findByText("Los nombres de los titulares están pendientes de publicación.");
  });

  test("the drawer's legal link closes the drawer and focuses the legal h1", async () => {
    renderAt("/metodologia");
    const menu = screen.getByRole("button", { name: "Abrir menú" });
    fireEvent.click(menu);
    fireEvent.click(within(sidebar()).getByRole("link", { name: "Aviso legal y privacidad" }));
    const h1 = await screen.findByRole("heading", { level: 1, name: "Aviso legal y privacidad" });
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    const canvas = screen.getByRole("main").closest(".app-shell__canvas") as HTMLElement;
    expect(canvas.hasAttribute("inert")).toBe(false);
    expect(document.activeElement).toBe(h1);
    await screen.findByText("Los nombres de los titulares están pendientes de publicación.");
  });

  test("the drawer's legal link on /legal closes the drawer and returns focus to the menu", async () => {
    renderAt("/legal");
    await screen.findByText("Los nombres de los titulares están pendientes de publicación.");
    const menu = screen.getByRole("button", { name: "Abrir menú" });
    fireEvent.click(menu);
    fireEvent.click(within(sidebar()).getByRole("link", { name: "Aviso legal y privacidad" }));
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(menu);
  });

  test("the Questionnaire has no sidebar", () => {
    renderAt("/elecciones/1/cuestionario");
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.queryByRole("button", { name: "Abrir menú" })).toBeNull();
  });
});
