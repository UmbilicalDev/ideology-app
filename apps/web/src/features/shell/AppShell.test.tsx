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

// donate-buymeacoffee Scenario 1: `Invítanos a un café` under `Danos tu
// opinión` on every shell page, only when configured. Fictitious profile only.
describe("AppShell donation link", () => {
  const PROFILE = "https://www.buymeacoffee.com/perfil_de_prueba";
  const LINK_NAME = "Invítanos a un café (se abre en una pestaña nueva)";

  function renderWithDonation(path: string, donation: unknown) {
    const fetch = vi.fn<FetchLike>(async (url) => {
      if (url === "/api/v1/donation") return jsonResponse(donation);
      if (url === "/api/v1/legal-notice") return jsonResponse({ holders: [], contact_email: null, address: null });
      if (url === "/api/v1/elections") return jsonResponse({ elections: [electionJson()] });
      return jsonResponse({ error: {} }, 404);
    });
    render(
      <MemoryRouter initialEntries={[path]}>
        <App api={createPublicApiClient({ fetch })} />
      </MemoryRouter>,
    );
    return fetch;
  }

  function footerItems(): string[] {
    const footer = sidebar().querySelector(".sidebar__footer") as HTMLElement;
    return Array.from(footer.children).map((el) => el.textContent ?? "");
  }

  test.each(["/", "/metodologia", "/transparencia", "/legal", "/no-existe", "/resultados#v1-1-dddddA"])(
    "at %s the sidebar footer is Danos tu opinión, the donation link, then the legal link",
    async (path) => {
      renderWithDonation(path, { url: PROFILE });
      const link = await within(sidebar()).findByRole("link", { name: LINK_NAME });
      expect(footerItems()).toEqual([
        "Danos tu opinión",
        "Invítanos a un café (se abre en una pestaña nueva)",
        "Aviso legal y privacidad",
      ]);
      expect(link.className).toBe("sidebar__donate-link");
      expect(link.getAttribute("href")).toBe(PROFILE);
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
      // No disclosure in the sidebar, and no link in the canvas footer.
      expect(sidebar().querySelector("details")).toBeNull();
      expect(within(screen.getByRole("contentinfo")).queryByRole("link", { name: LINK_NAME })).toBeNull();
      await screen.findAllByRole("heading", { level: 1 });
    },
  );

  test("the other host form is used exactly as configured", async () => {
    renderWithDonation("/", { url: "https://buymeacoffee.com/perfil_de_prueba" });
    const link = await within(sidebar()).findByRole("link", { name: LINK_NAME });
    expect(link.getAttribute("href")).toBe("https://buymeacoffee.com/perfil_de_prueba");
  });

  test.each([
    ["null", { url: null }],
    ["a contract break", { url: "javascript:alert(1)" }],
  ])("%s: no donation link and no empty slot", async (_name, donation) => {
    const fetch = renderWithDonation("/metodologia", donation);
    await vi.waitFor(() => expect(fetch.mock.calls.some(([u]) => u === "/api/v1/donation")).toBe(true));
    await Promise.resolve();
    expect(footerItems()).toEqual(["Danos tu opinión", "Aviso legal y privacidad"]);
    expect(screen.queryByRole("link", { name: LINK_NAME })).toBeNull();
  });

  test("activating the drawer's link keeps the drawer open and the page unchanged", async () => {
    renderWithDonation("/metodologia", { url: PROFILE });
    const menu = screen.getByRole("button", { name: "Abrir menú" });
    fireEvent.click(menu);
    const link = await within(sidebar()).findByRole("link", { name: LINK_NAME });
    fireEvent.click(link);
    expect(menu.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("banner").textContent).toBe("IdeologiApp/Cómo funciona");
  });
});
