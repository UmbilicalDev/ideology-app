import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { METHODOLOGY_PATH } from "../paths";

const NBSP = " ";

const HEADINGS = [
  "Programas electorales",
  "Cómo se redactan las afirmaciones",
  "Cómo se sitúa a cada partido",
  "Comprobaciones antes de publicar",
  "Cómo se calcula la afinidad",
  "Tus respuestas",
  "Aviso",
];

const INTRO_TEXT =
  "Esta página explica de dónde salen las afirmaciones y las posiciones de los partidos, cómo " +
  "se comprueban antes de publicarse, cómo se calcula la afinidad y qué pasa con tus respuestas.";

const SOURCES_PROMPT_TEXT =
  "Las instrucciones que recibe la inteligencia artificial nunca incluyen el nombre del " +
  "partido: solo el texto de su programa, que puede mencionarlo. Todos los programas se " +
  "procesan con las mismas instrucciones.";

const PRIVACY_TEXT =
  "Tus respuestas se quedan en tu navegador: no se envían ni se guardan en ningún servidor, y " +
  "la afinidad se calcula en tu propio dispositivo. No hay cuentas de usuario ni estadísticas " +
  "sobre las respuestas.";

const SHARE_TEXT =
  "Puedes compartir tu resultado con un enlace que lleva tus respuestas al final de la " +
  "dirección, tras el símbolo «#». Los navegadores no envían esa parte de la dirección al " +
  "servidor y el enlace no se guarda en ningún sitio: quien lo tenga puede ver tus respuestas.";

const DISCLAIMER_TEXT =
  "Esta herramienta no es una recomendación de voto. Las afirmaciones y las posiciones las " +
  "genera automáticamente una inteligencia artificial, sin revisión humana, y pueden contener " +
  "errores. La afinidad solo refleja lo que dicen los programas electorales, no lo que los " +
  "partidos han hecho o votado. Contrasta las citas con los programas originales antes de " +
  "sacar conclusiones.";

function renderMethodology() {
  const fetch = vi.fn<FetchLike>();
  render(
    <MemoryRouter initialEntries={[METHODOLOGY_PATH]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
  return fetch;
}

describe("MethodologyPage", () => {
  test("renders at /metodologia with the h1 focused and the methodology title", () => {
    renderMethodology();
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Metodología");
    expect(document.activeElement).toBe(h1);
    expect(document.title).toBe("Metodología · Comparador de programas electorales");
    expect(screen.getByText(INTRO_TEXT)).toBeTruthy();
  });

  test("has the seven sections in order, each a named region", () => {
    renderMethodology();
    const h2s = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(h2s).toEqual(HEADINGS);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    for (const name of HEADINGS) {
      expect(screen.getByRole("region", { name })).toBeTruthy();
    }
    expect(screen.getAllByRole("region")).toHaveLength(7);
  });

  test("states that prompts never add party names, without claiming the text omits them", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Programas electorales" });
    expect(within(region).getByText(SOURCES_PROMPT_TEXT)).toBeTruthy();
    expect(screen.queryByText(/nunca recibe el nombre del partido/)).toBeNull();
  });

  test("lists the six Validation checks with the default coverage threshold", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Comprobaciones antes de publicar" });
    const items = within(region).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    expect(items[1]?.textContent).toBe(
      `cada partido tiene posición en al menos el 70${NBSP}% de las afirmaciones;`,
    );
    expect(items[4]?.textContent).toBe("el cuestionario tiene entre 25 y 35 afirmaciones;");
    expect(items[5]?.textContent).toBe(
      `ningún tema reúne más del 30${NBSP}% de las afirmaciones.`,
    );
  });

  test("states the privacy model and the disclaimer inside the Aviso card", () => {
    renderMethodology();
    const privacy = screen.getByRole("region", { name: "Tus respuestas" });
    expect(within(privacy).getByText(PRIVACY_TEXT)).toBeTruthy();
    expect(within(privacy).getByText(SHARE_TEXT)).toBeTruthy();
    expect(privacy.textContent).not.toContain("se usará");
    const disclaimer = screen.getByRole("region", { name: "Aviso" });
    expect(disclaimer.className).toBe("card");
    expect(within(disclaimer).getByText(DISCLAIMER_TEXT)).toBeTruthy();
  });

  test("the only link is Volver al inicio, there are no images and no request", () => {
    const fetch = renderMethodology();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]?.textContent).toBe("Volver al inicio");
    expect(links[0]?.getAttribute("href")).toBe("/");
    expect(screen.getByRole("main").querySelectorAll("img, svg")).toHaveLength(0);
    expect(fetch).not.toHaveBeenCalled();
  });
});
