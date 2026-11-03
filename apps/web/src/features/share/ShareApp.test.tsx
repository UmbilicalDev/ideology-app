import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike, type HttpResponseLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { datasetVersionJson, electionJson, jsonResponse } from "../../test/fetch-mocks";
import { appShareLinks, SHARE_TEXT } from "./app-share-links";

const INTRO = "¿Te ha gustado IdeologiApp? Recomienda esta web a otras personas.";
const COPIED = "Enlace de IdeologiApp copiado.";
const COPIED_INSTAGRAM = "Enlace de IdeologiApp copiado. Ya puedes pegarlo en Instagram.";
const FALLBACK = "No se ha podido copiar el enlace automáticamente. Cópialo desde este campo:";
const FALLBACK_INSTAGRAM =
  "No se ha podido copiar el enlace automáticamente. Cópialo desde este campo y pégalo en " +
  "Instagram:";

const TARGETS = [
  { caption: "Copiar enlace", name: "Copiar enlace de IdeologiApp", tag: "BUTTON" },
  { caption: "Facebook", name: "Compartir IdeologiApp en Facebook", tag: "A" },
  { caption: "WhatsApp", name: "Compartir IdeologiApp en WhatsApp", tag: "A" },
  { caption: "Instagram", name: "Compartir IdeologiApp en Instagram", tag: "BUTTON" },
  { caption: "X", name: "Compartir IdeologiApp en X", tag: "A" },
  { caption: "Correo", name: "Compartir IdeologiApp por correo electrónico", tag: "A" },
] as const;

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

function renderAt(path: string, fetch: FetchLike) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
}

function button(name: string) {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

/** Opens the six-Statement Questionnaire and rates (or skips) every Statement. */
async function finish({ skipAll = false } = {}) {
  const fetch = sixStatementFetch();
  renderAt("/elecciones/1/cuestionario", fetch);
  await screen.findByRole("radiogroup");
  for (let i = 0; i < 6; i += 1) {
    if (skipAll) {
      fireEvent.click(button("Saltar esta afirmación"));
    } else {
      fireEvent.click(screen.getByRole("radio", { name: i === 5 ? "Muy en desacuerdo" : "De acuerdo" }));
      fireEvent.click(button("Siguiente"));
    }
  }
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Tus resultados");
  return fetch;
}

function appSection() {
  return screen.getByRole("region", { name: "Comparte IdeologiApp" });
}

function target(name: string) {
  const section = within(appSection());
  return (section.queryByRole("button", { name }) ?? section.getByRole("link", { name })) as HTMLElement;
}

function defineClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", { value, configurable: true });
}

function defineShare(value: unknown) {
  Object.defineProperty(navigator, "share", { value, configurable: true, writable: true });
}

function domError(name: string): Error {
  const error = new Error(name);
  error.name = name;
  return error;
}

const home = () => `${window.location.origin}/`;

let clicks: HTMLAnchorElement[] = [];
let added: Element[] = [];
let observer: MutationObserver | undefined;

/** jsdom does not navigate; record and cancel link activations instead. */
function stopNavigation(event: MouseEvent) {
  const anchor = (event.target as Element | null)?.closest("a");
  if (anchor !== null && anchor !== undefined) {
    clicks.push(anchor);
    event.preventDefault();
  }
}

beforeEach(() => {
  clicks = [];
  added = [];
  document.addEventListener("click", stopNavigation);
});

afterEach(() => {
  document.removeEventListener("click", stopNavigation);
  observer?.disconnect();
  observer = undefined;
  // vi.unstubAllGlobals does not restore a defined navigator property.
  delete (navigator as { clipboard?: unknown }).clipboard;
  delete (navigator as { share?: unknown }).share;
});

function watchAddedResources() {
  observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        for (const element of [node, ...node.querySelectorAll("*")]) {
          if (["SCRIPT", "IMG", "IFRAME", "LINK"].includes(element.tagName)) added.push(element);
        }
      }
    }
  });
  observer.observe(document, { childList: true, subtree: true });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("ShareApp on the end screen", () => {
  test("Scenario 1: one card holds Comparte tu resultado, then Comparte IdeologiApp with six targets", async () => {
    await finish();
    const result = screen.getByRole("region", { name: "Comparte tu resultado" });
    const app = appSection();
    const card = result.parentElement!;
    expect(card.className).toBe("share-card");
    expect(app.parentElement).toBe(card);
    expect(result.nextElementSibling).toBe(app);
    expect(app.className).toBe("share-app");

    const title = within(app).getByRole("heading", { level: 3, name: "Comparte IdeologiApp" });
    expect(title.querySelector("svg")).toBeNull();
    expect(within(app).getByText(INTRO).tagName).toBe("P");

    const items = within(within(app).getByRole("list")).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    const controls = items.map((li) => li.firstElementChild as HTMLElement);
    expect(controls.map((el) => el.getAttribute("aria-label"))).toEqual(TARGETS.map((t) => t.name));
    expect(controls.map((el) => el.tagName)).toEqual(TARGETS.map((t) => t.tag));
    expect(controls.map((el) => el.querySelector(".share-target__label")?.textContent)).toEqual(
      TARGETS.map((t) => t.caption),
    );
    for (const [i, el] of controls.entries()) {
      // WCAG 2.5.3: the accessible name contains the visible caption (case-insensitive).
      expect(el.getAttribute("aria-label")!.toLowerCase()).toContain(TARGETS[i]!.caption.toLowerCase());
      expect(el.className).toBe("share-target");
    }
    // The exact name Copiar enlace stays unique to the result part.
    expect(screen.getAllByRole("button", { name: "Copiar enlace" })).toHaveLength(1);
    expect(within(app).getByRole("status").textContent).toBe("");
  });

  test("Scenario 2: Copiar enlace de IdeologiApp copies the home URL; the result status stays empty", async () => {
    const writeText = vi.fn(async (_text: string) => undefined);
    defineClipboard({ writeText });
    const fetch = await finish();
    const calls = fetch.mock.calls.length;
    fireEvent.click(target("Copiar enlace de IdeologiApp"));
    expect(await within(appSection()).findByText(COPIED)).toBe(within(appSection()).getByRole("status"));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(home());
    const result = screen.getByRole("region", { name: "Comparte tu resultado" });
    expect(within(result).getByRole("status").textContent).toBe("");
    expect(within(appSection()).queryByRole("textbox")).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(calls);
  });

  test.each([
    ["missing", undefined],
    ["denied", { writeText: vi.fn(async () => Promise.reject(domError("NotAllowedError"))) }],
  ])("Scenario 2: clipboard %s shows the home URL in a focused, selected field", async (_, clipboard) => {
    defineClipboard(clipboard);
    await finish();
    fireEvent.click(target("Copiar enlace de IdeologiApp"));
    const field = (await within(appSection()).findByRole("textbox", {
      name: "Enlace de IdeologiApp",
    })) as HTMLInputElement;
    expect(field.id).toBe("share-app-url");
    expect(field.className).toBe("share__field");
    expect(field.readOnly).toBe(true);
    expect(field.value).toBe(home());
    expect(document.activeElement).toBe(field);
    expect([field.selectionStart, field.selectionEnd]).toEqual([0, home().length]);
    expect(within(appSection()).getByRole("status").textContent).toBe(FALLBACK);
  });

  test("Scenario 3: Facebook, WhatsApp and X open the builder's URLs in a new tab; Correo in place; nothing loads", async () => {
    const fetch = await finish();
    const links = appShareLinks(window.location.origin);
    const newTab = within(appSection()).getByText("(se abre en una pestaña nueva)");
    expect(newTab.className).toBe("visually-hidden");
    for (const [name, href] of [
      ["Compartir IdeologiApp en Facebook", links.facebook],
      ["Compartir IdeologiApp en WhatsApp", links.whatsapp],
      ["Compartir IdeologiApp en X", links.x],
    ] as const) {
      const link = target(name);
      expect(link.getAttribute("href")).toBe(href);
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
      expect(link.getAttribute("aria-describedby")).toBe(newTab.id);
    }
    const mail = target("Compartir IdeologiApp por correo electrónico");
    expect(mail.getAttribute("href")).toBe(links.email);
    expect(mail.hasAttribute("target")).toBe(false);

    const calls = fetch.mock.calls.length;
    watchAddedResources();
    for (const name of [
      "Compartir IdeologiApp en Facebook",
      "Compartir IdeologiApp en WhatsApp",
      "Compartir IdeologiApp en X",
      "Compartir IdeologiApp por correo electrónico",
    ]) {
      fireEvent.click(target(name));
    }
    await flush();
    expect(clicks).toHaveLength(4);
    expect(fetch).toHaveBeenCalledTimes(calls);
    expect(added).toEqual([]);
    // The answers stay in memory: Revisar mis respuestas still opens Statement 1, rated.
    fireEvent.click(button("Revisar mis respuestas"));
    expect((screen.getByRole("radio", { name: "De acuerdo" }) as HTMLInputElement).checked).toBe(true);
  });

  test("Scenario 4: Instagram with navigator.share resolving shares once; no copy, empty status", async () => {
    const share = vi.fn(async (_data: ShareData) => undefined);
    const writeText = vi.fn(async (_text: string) => undefined);
    defineShare(share);
    defineClipboard({ writeText });
    await finish();
    fireEvent.click(target("Compartir IdeologiApp en Instagram"));
    await flush();
    expect(share).toHaveBeenCalledTimes(1);
    expect(share).toHaveBeenCalledWith({ title: "IdeologiApp", text: SHARE_TEXT, url: home() });
    expect(writeText).not.toHaveBeenCalled();
    expect(within(appSection()).getByRole("status").textContent).toBe("");
  });

  test.each([
    ["rejecting", () => Promise.reject(domError("AbortError"))],
    [
      "throwing",
      () => {
        throw domError("AbortError");
      },
    ],
  ])("Scenario 4: Instagram cancelled (%s AbortError) is silent", async (_, impl) => {
    const share = vi.fn(impl);
    const writeText = vi.fn(async (_text: string) => undefined);
    defineShare(share);
    defineClipboard({ writeText });
    await finish();
    fireEvent.click(target("Compartir IdeologiApp en Instagram"));
    await flush();
    expect(share).toHaveBeenCalledTimes(1);
    expect(writeText).not.toHaveBeenCalled();
    expect(within(appSection()).getByRole("status").textContent).toBe("");
    expect(within(appSection()).queryByRole("textbox")).toBeNull();
  });

  test.each([
    ["NotAllowedError", () => defineShare(vi.fn(async () => Promise.reject(domError("NotAllowedError"))))],
    ["TypeError", () => defineShare(vi.fn(async () => Promise.reject(new TypeError("bad data"))))],
    ["no navigator.share", () => undefined],
  ])("Scenario 4: Instagram with %s copies the home URL with the Instagram message", async (_, setUp) => {
    setUp();
    const writeText = vi.fn(async (_text: string) => undefined);
    defineClipboard({ writeText });
    await finish();
    fireEvent.click(target("Compartir IdeologiApp en Instagram"));
    expect(await within(appSection()).findByText(COPIED_INSTAGRAM)).toBeTruthy();
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(home());
  });

  test("Scenario 4: Instagram without share and without clipboard shows the Instagram field message", async () => {
    defineClipboard(undefined);
    await finish();
    fireEvent.click(target("Compartir IdeologiApp en Instagram"));
    const field = (await within(appSection()).findByRole("textbox", {
      name: "Enlace de IdeologiApp",
    })) as HTMLInputElement;
    expect(field.value).toBe(home());
    expect(document.activeElement).toBe(field);
    expect(within(appSection()).getByRole("status").textContent).toBe(FALLBACK_INSTAGRAM);
  });

  test("Scenario 6: all Statements skipped shows only Comparte IdeologiApp", async () => {
    await finish({ skipAll: true });
    expect(screen.queryByRole("region", { name: "Comparte tu resultado" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copiar enlace" })).toBeNull();
    const app = appSection();
    expect(app.parentElement?.className).toBe("share-card");
    expect(app.parentElement?.children).toHaveLength(1);
  });

  test("Scenario 9: icons are aria-hidden and use only currentColor; targets are focusable in order", async () => {
    await finish();
    const app = appSection();
    const icons = app.querySelectorAll("svg");
    expect(icons).toHaveLength(6);
    for (const svg of icons) {
      expect(svg.getAttribute("aria-hidden")).toBe("true");
      expect(svg.getAttribute("focusable")).toBe("false");
      for (const el of [svg, ...svg.querySelectorAll("*")]) {
        for (const attr of ["fill", "stroke", "color", "stop-color", "style"]) {
          const value = el.getAttribute(attr);
          if (value !== null) expect(["currentColor", "none"]).toContain(value);
        }
      }
    }
    // DOM order is the Tab order: native buttons and links with an href, no tabindex.
    const controls = Array.from(app.querySelectorAll<HTMLElement>("button, a[href]"));
    expect(controls.map((el) => el.getAttribute("aria-label"))).toEqual(TARGETS.map((t) => t.name));
    for (const el of controls) {
      expect(el.getAttribute("tabindex")).toBeNull();
      el.focus();
      expect(document.activeElement).toBe(el);
    }
  });
});

describe("ShareApp never leaks Answers (Scenario 5)", () => {
  let previous = "";
  beforeEach(() => {
    previous = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  });
  afterEach(() => {
    cleanup();
    window.history.replaceState(null, "", previous);
  });

  test("with the address bar at /resultados#v1-1-dddddA, every URL, the clipboard and the share data hold only the home URL", async () => {
    const fetch = routes({
      "/api/v1/elections/1": () => jsonResponse(electionJson()),
      "/api/v1/dataset-versions/1": () => jsonResponse(datasetVersionJson({ statements: 6 })),
    });
    window.history.replaceState(null, "", "/resultados#v1-1-dddddA");
    const writeText = vi.fn(async (_text: string) => undefined);
    const share = vi.fn(async (_data: ShareData) => Promise.reject(domError("NotAllowedError")));
    defineClipboard({ writeText });
    defineShare(share);
    renderAt("/resultados#v1-1-dddddA", fetch);
    await screen.findByRole("heading", { level: 2, name: "Afinidad con cada partido" });

    fireEvent.click(target("Copiar enlace de IdeologiApp"));
    await within(appSection()).findByText(COPIED);
    fireEvent.click(target("Compartir IdeologiApp en Instagram"));
    await within(appSection()).findByText(COPIED_INSTAGRAM);

    const hrefs = Array.from(appSection().querySelectorAll("a")).map((a) => a.getAttribute("href")!);
    const texts = [
      ...hrefs,
      ...writeText.mock.calls.map((call) => call[0]),
      ...share.mock.calls.map((call) => JSON.stringify(call[0])),
    ];
    expect(hrefs).toHaveLength(4);
    expect(writeText.mock.calls.map((call) => call[0])).toEqual([home(), home()]);
    expect(share.mock.calls[0]![0].url).toBe(home());
    for (const text of texts) {
      expect(text).not.toContain("#");
      expect(text).not.toContain("resultados");
      expect(text).not.toContain("v1-");
      expect(text).not.toContain("dddddA");
    }
  });
});

describe("ShareApp on the shared result (Scenario 7)", () => {
  test("a ready link shows only Comparte IdeologiApp, between the CTA and the breakdown", async () => {
    renderAt("/resultados#v1-1-dddddA", sixStatementFetch());
    await screen.findByRole("heading", { level: 2, name: "Afinidad con cada partido" });
    const app = appSection();
    expect(screen.queryByRole("region", { name: "Comparte tu resultado" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copiar enlace" })).toBeNull();
    const card = app.parentElement!;
    expect(card.className).toBe("share-card");
    expect(card.children).toHaveLength(1);
    const cta = screen.getByRole("link", { name: "Haz tú el cuestionario" });
    expect(card.previousElementSibling).toBe(cta.parentElement);
    const breakdown = document.querySelector(".breakdown-row")!;
    expect(card.compareDocumentPosition(breakdown) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test.each(["/resultados", "/resultados#garbage"])("%s shows no share section", async (path) => {
    renderAt(path, sixStatementFetch());
    await screen.findByRole("link", { name: "Volver al inicio" });
    expect(screen.queryByRole("region", { name: "Comparte IdeologiApp" })).toBeNull();
    expect(document.querySelector(".share-card")).toBeNull();
  });
});
