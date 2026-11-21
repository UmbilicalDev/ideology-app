// donate-buymeacoffee: the donation link and block, through `App` with a
// URL-routed fetch. Fictitious profile only (`perfil_de_prueba`).
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike, type HttpResponseLike } from "@ideology-app/core";

import { App } from "../../app/App";
import {
  DONATION_PATH,
  apiPaths,
  datasetVersionJson,
  electionJson,
  jsonResponse,
  textResponse,
} from "../../test/fetch-mocks";
import { answerButton, findAnswerButtons } from "../../test/questionnaire";

const PROFILE = "https://www.buymeacoffee.com/perfil_de_prueba";
const ELECTION_URL = "/api/v1/elections/1";
const VERSION_URL = "/api/v1/dataset-versions/1";
const LINK_NAME = "Invítanos a un café (se abre en una pestaña nueva)";
const SUMMARY = "¿Para qué se usan las donaciones?";
const BODY = [
  "Donar es una forma sencilla de apoyar IdeologiApp y de ayudarla a crecer: con las donaciones añadimos funciones nuevas o mejoramos las que ya hay, y pagamos el alojamiento de la web.",
  "No aceptamos donaciones hechas en nombre de partidos políticos. Si detectamos una donación hecha en nombre de un partido político, la devolveremos.",
];

type Donation = () => HttpResponseLike | Promise<HttpResponseLike>;

function questionnaireFetch(donation: Donation) {
  return vi.fn<FetchLike>(async (url) => {
    if (url === DONATION_PATH) return donation();
    if (url === ELECTION_URL) return jsonResponse(electionJson());
    if (url === VERSION_URL) return jsonResponse(datasetVersionJson({ statements: 3 }));
    throw new Error(`unexpected request ${url}`);
  });
}

let currentUrl = "";
function LocationProbe() {
  const location = useLocation();
  currentUrl = `${location.pathname}${location.search}${location.hash}`;
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

async function reachResults(fetch: FetchLike) {
  renderAt("/elecciones/1/cuestionario", fetch);
  await findAnswerButtons();
  for (let i = 0; i < 3; i += 1) {
    if (i === 1) fireEvent.click(screen.getByRole("button", { name: "Importante para mí" }));
    fireEvent.click(answerButton("De acuerdo"));
  }
  expect(screen.getByRole("heading", { level: 2, name: "Tus resultados" })).toBeTruthy();
}

function rankingTexts(): string[] {
  return Array.from(document.querySelectorAll(".ranking-row")).map((li) => li.textContent ?? "");
}

describe("donation block at the end of the results", () => {
  test("Scenario 2: the last element is the line, the link and the closed disclosure", async () => {
    await reachResults(questionnaireFetch(() => jsonResponse({ url: PROFILE })));
    const block = await screen.findByText((_, el) => el?.className === "donate-block");
    // Last child of the end screen, after the breakdown.
    expect(block.nextElementSibling).toBeNull();
    expect(block.previousElementSibling?.classList.contains("breakdown-section")).toBe(true);

    const line = block.querySelector("p.donate-block__line") as HTMLElement;
    expect(line.textContent).toBe("¿Quieres apoyar el proyecto? Invítanos a un café (se abre en una pestaña nueva)");
    const link = within(line).getByRole("link", { name: LINK_NAME });
    expect(link.textContent).toBe("Invítanos a un café (se abre en una pestaña nueva)");
    expect(link.getAttribute("href")).toBe(PROFILE);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.className).toBe("text-link");
    expect(link.querySelectorAll("svg[aria-hidden='true']")).toHaveLength(2);

    const details = block.querySelector("details") as HTMLDetailsElement;
    expect(details.nextElementSibling).toBeNull();
    expect(line.nextElementSibling).toBe(details);
    expect(details.open).toBe(false);
    const summary = details.querySelector("summary") as HTMLElement;
    expect(summary.textContent).toBe(SUMMARY);
    expect(Array.from(details.querySelectorAll("p")).map((p) => p.textContent?.replace(/\s+/g, " "))).toEqual(BODY);

    // Pointer: open, then close.
    fireEvent.click(summary);
    expect(details.open).toBe(true);
    fireEvent.click(summary);
    expect(details.open).toBe(false);
    // The keyboard path is the native summary activation (checked in the
    // browser); jsdom toggles through the property and the toggle event.
    details.open = true;
    expect(details.open).toBe(true);
    details.open = false;
    expect(details.open).toBe(false);
  });

  test("Scenario 2: the link carries nothing, and activating it keeps the URL, history, ranking and Answers", async () => {
    const fetch = questionnaireFetch(() => jsonResponse({ url: PROFILE }));
    await reachResults(fetch);
    const link = await screen.findByRole("link", { name: LINK_NAME });
    const before = { url: currentUrl, history: window.history.length, ranking: rankingTexts() };
    fireEvent.click(link);
    expect(link.getAttribute("href")).toBe(PROFILE);
    expect({ url: currentUrl, history: window.history.length, ranking: rankingTexts() }).toEqual(before);
    expect(currentUrl).toBe("/elecciones/1/cuestionario");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    // No request after the results, and none carries the Answers.
    expect(fetch.mock.calls.map((call) => call[0])).toEqual(
      expect.arrayContaining([ELECTION_URL, VERSION_URL, DONATION_PATH]),
    );
    expect(fetch).toHaveBeenCalledTimes(3);
    // The Answers survive: the end screen is still there, with the same ranking.
    expect(screen.getByRole("heading", { level: 2, name: "Tus resultados" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Repetir cuestionario" })).toBeTruthy();
  });

  test.each<[string, Donation]>([
    ["null", () => jsonResponse({ url: null })],
    ["a 500", () => textResponse(500)],
    ["a contract break", () => jsonResponse({ url: "https://www.buymeacoffee.com/perfil?ref=x" })],
    ["a missing url", () => jsonResponse({})],
    ["a network error", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["an unanswered request", () => new Promise<HttpResponseLike>(() => {})],
  ])("Scenario 4: %s renders no block, no link and no disclosure", async (_name, donation) => {
    await reachResults(questionnaireFetch(donation));
    await Promise.resolve();
    expect(document.querySelector(".donate-block")).toBeNull();
    expect(screen.queryByText("¿Quieres apoyar el proyecto?")).toBeNull();
    expect(screen.queryByText(SUMMARY)).toBeNull();
    expect(screen.queryByRole("link", { name: LINK_NAME })).toBeNull();
    expect(document.body.innerHTML).not.toContain("buymeacoffee");
  });

  test("nothing from another origin is rendered: no img, iframe or script", async () => {
    await reachResults(questionnaireFetch(() => jsonResponse({ url: PROFILE })));
    await screen.findByRole("link", { name: LINK_NAME });
    for (const element of Array.from(document.querySelectorAll("img, iframe, script, link"))) {
      const src = element.getAttribute("src") ?? element.getAttribute("href") ?? "";
      expect(src).not.toMatch(/^https?:\/\//);
    }
    expect(document.querySelectorAll("iframe, script")).toHaveLength(0);
    // The profile URL appears only as the one link's href.
    const hrefs = Array.from(document.querySelectorAll(`[href="${PROFILE}"]`));
    expect(hrefs).toHaveLength(1);
  });
});

describe("donation request", () => {
  test("an App mount sends exactly one bare GET /api/v1/donation", async () => {
    const fetch = vi.fn<FetchLike>(async (url) =>
      url === DONATION_PATH ? jsonResponse({ url: PROFILE }) : jsonResponse({ elections: [] }),
    );
    renderAt("/metodologia", fetch);
    await screen.findByRole("link", { name: LINK_NAME });
    expect(fetch.mock.calls).toEqual([
      [DONATION_PATH, { method: "GET", headers: { Accept: "application/json" } }],
    ]);
    expect(apiPaths(fetch)).toEqual([]);
    // Navigating inside the app does not ask again.
    fireEvent.click(within(screen.getByRole("complementary")).getByRole("link", { name: "Transparencia IA" }));
    await screen.findByRole("heading", { level: 1 });
    expect(fetch.mock.calls.filter(([url]) => url === DONATION_PATH)).toHaveLength(1);
  });
});
