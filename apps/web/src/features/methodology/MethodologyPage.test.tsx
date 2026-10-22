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
  "Cómo se eligen las afirmaciones del cuestionario",
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
  "servidor y el enlace no se guarda en ningún sitio: quien lo tenga puede ver tus respuestas. " +
  "Al abrir el enlace se ve el mismo resultado, calculado de nuevo en el navegador con la misma " +
  "versión del cuestionario; si después se ha publicado una más reciente, se avisa.";

const DISCLAIMER_TEXT =
  "Esta herramienta no es una recomendación de voto. Las afirmaciones y las posiciones las " +
  "genera automáticamente una inteligencia artificial, sin revisión humana, y pueden contener " +
  "errores. La afinidad solo refleja lo que dicen los programas electorales, no lo que los " +
  "partidos han hecho o votado. Contrasta las citas con los programas originales antes de " +
  "sacar conclusiones.";

const STATEMENTS_TEXT =
  "Una inteligencia artificial lee los programas por fragmentos y propone afirmaciones: " +
  "propuestas políticas concretas con las que se puede estar de acuerdo o en desacuerdo. " +
  "Después elige y redacta una lista más amplia, de unas 55 afirmaciones candidatas, y asigna " +
  "a cada una un tema.";

const STATEMENTS_RULES_TEXT =
  "Sus instrucciones le piden una redacción neutral, sin adjetivos valorativos ni nombres de " +
  "partidos o de políticos, una sola propuesta por afirmación, temas variados y, " +
  "preferiblemente, propuestas en las que los partidos discrepen y propuestas que traten " +
  "varios programas. Nadie modifica a mano el resultado.";

const SELECTION_TEXTS = [
  "La inteligencia artificial propone más afirmaciones de las que tendrá el cuestionario, " +
    "entre 45 y 60, y sitúa a cada partido en todas ellas. Después, un procedimiento " +
    "automático, sin inteligencia artificial y sin azar, elige entre 25 y 35 para el " +
    "cuestionario.",
  "Deja fuera las afirmaciones repetidas y las que no separan a los partidos, porque todos " +
    `los que tienen posición coinciden, y no deja que un tema supere el 30${NBSP}% del ` +
    "cuestionario. Entre las demás, elige primero las que dan posición al partido que menos " +
    "tiene hasta ese momento; en caso de empate, las que muestran más posiciones distintas y, " +
    "después, las que se propusieron antes. Todos los partidos cuentan igual.",
  "El cuestionario tiene el mayor número de afirmaciones con el que todos los partidos tienen " +
    `posición en al menos el 70${NBSP}% de ellas. Si no es posible cumplir estas condiciones, ` +
    "el procedimiento se acerca todo lo que puede y las comprobaciones posteriores impiden " +
    "publicar el resultado. Las afirmaciones conservan el texto y el orden con que se " +
    "propusieron.",
];

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

  test("has the eight sections in order, each a named region", () => {
    renderMethodology();
    const h2s = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(h2s).toEqual(HEADINGS);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    for (const name of HEADINGS) {
      expect(screen.getByRole("region", { name })).toBeTruthy();
    }
    expect(screen.getAllByRole("region")).toHaveLength(8);
  });

  test("describes the candidate pool when the statements are written", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Cómo se redactan las afirmaciones" });
    expect(within(region).getByText(STATEMENTS_TEXT)).toBeTruthy();
    expect(within(region).getByText(STATEMENTS_RULES_TEXT)).toBeTruthy();
    expect(screen.queryByText(/unas 30 afirmaciones/)).toBeNull();
  });

  test("explains the deterministic selection of the questionnaire", () => {
    renderMethodology();
    const region = screen.getByRole("region", {
      name: "Cómo se eligen las afirmaciones del cuestionario",
    });
    const paragraphs = within(region)
      .getAllByText((_, element) => element?.tagName === "P")
      .map((p) => p.textContent);
    expect(paragraphs).toEqual(SELECTION_TEXTS);
  });

  test("states that prompts never add party names, without claiming the text omits them", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Programas electorales" });
    expect(within(region).getByText(SOURCES_PROMPT_TEXT)).toBeTruthy();
    expect(screen.queryByText(/nunca recibe el nombre del partido/)).toBeNull();
  });

  test("says the results let the Voter open each Position to read its quote", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Cómo se sitúa a cada partido" });
    expect(
      within(region).getByText(
        /^En los resultados puedes abrir la posición de cada partido en cada afirmación para leer la cita y comprobarla\./,
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/Podrás consultar la cita/)).toBeNull();
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
