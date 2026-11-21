import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { METHODOLOGY_PATH } from "../paths";
import { apiPaths } from "../../test/fetch-mocks";

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
  "versión del cuestionario; si después se ha publicado una más reciente, se avisa. Los enlaces " +
  "creados antes del cuestionario de tres opciones muestran un aviso en lugar del resultado.";

const FEEDBACK_TEXT =
  "Si nos envías tu opinión sobre la herramienta, se guarda solo el texto que escribas, desde " +
  "dónde la envías (el menú general o la pantalla de resultados) y la fecha. No se guardan " +
  "tus respuestas, tu dirección IP ni ningún otro dato sobre ti. Para frenar los envíos " +
  "masivos, el servidor cuenta durante unos minutos, solo en memoria, los envíos de cada " +
  "conexión. No escribas datos personales en el mensaje.";

const LEGAL_LINK_TEXT =
  "Quién es responsable, cuánto tiempo se guardan las opiniones y cómo ejercer tus derechos se " +
  "explica en Aviso legal y privacidad.";

const DISCLAIMER_TEXT =
  "Esta herramienta no es una recomendación de voto. Las afirmaciones y las posiciones las " +
  "genera automáticamente una inteligencia artificial, sin revisión humana, y pueden contener " +
  "errores. La afinidad solo refleja lo que dicen los programas electorales, no lo que los " +
  "partidos han hecho o votado. Contrasta las citas con los programas originales antes de " +
  "sacar conclusiones.";

const STATEMENTS_TEXTS = [
  "Una inteligencia artificial lee los programas por fragmentos y propone afirmaciones " +
    "candidatas: propuestas políticas con las que se puede estar de acuerdo o en desacuerdo. " +
    "Después, un procedimiento automático, sin inteligencia artificial y sin azar, toma el " +
    "mismo número de candidatas de cada partido, sea cual sea la extensión de su programa, " +
    "repartidas entre los temas que más trata cada programa. Un partido con menos candidatas " +
    "aporta todas las que tiene.",
  "Con esas candidatas, la inteligencia artificial redacta una lista más amplia, de unas 70 " +
    "afirmaciones, y asigna a cada una un tema. Cada afirmación expresa una orientación " +
    "política con una dirección clara, como subir o bajar un impuesto, y no una medida de " +
    "detalle, para que el mayor número posible de partidos se pueda situar en ella. Debe " +
    "entenderse por sí sola y en lenguaje llano: expresa la medida por su contenido y en " +
    "positivo, de modo que estar de acuerdo signifique querer esa medida, sin dobles " +
    "negaciones; solo habla de derogar o suprimir algo cuando la propuesta no tiene otro " +
    "contenido.",
  // pipeline-statement-clarity-context: anchors and context notes.
  "La inteligencia artificial recibe también las afirmaciones del cuestionario publicado " +
    "anteriormente y las vuelve a redactar con estas reglas, para que los temas que ya conoces " +
    "no desaparezcan por azar. Siguen en el cuestionario solo si superan el mismo procedimiento " +
    "de elección que las demás.",
  "Cada afirmación lleva una breve nota de contexto, también redactada por la inteligencia " +
    "artificial, que explica de forma neutral qué es la ley, el plan, la institución o el " +
    "concepto que nombra. La nota no sale de los programas, y las comprobaciones automáticas no " +
    "pueden confirmar que sea exacta; sus instrucciones le piden solo hechos descriptivos, sin " +
    "valoraciones ni nombres de partidos.",
  "Sus instrucciones le piden una redacción neutral, sin adjetivos valorativos ni nombres de " +
    "partidos o de políticos, una sola propuesta por afirmación, temas variados, orientaciones " +
    "en las que los partidos discrepen y no añadir nada que no esté en las candidatas ni en las " +
    "afirmaciones anteriores. Nadie modifica a mano el resultado.",
];

const POSITIONS_NO_STANCE_TEXT =
  "Si el programa no trata una afirmación, el partido queda sin posición en ella: sus " +
  "instrucciones le prohíben deducir la posición de la ideología general del partido o de " +
  "que el programa no mencione el asunto. Sí cuenta como tratarla una propuesta concreta del " +
  "programa que va claramente en la dirección de la afirmación o en la contraria, y la cita " +
  "debe contener esa propuesta.";

const SELECTION_TEXTS = [
  "La inteligencia artificial propone más afirmaciones de las que tendrá el cuestionario, " +
    "entre 60 y 80, y sitúa a cada partido en todas ellas. Después, un procedimiento " +
    "automático, sin inteligencia artificial y sin azar, elige entre 25 y 35 para el " +
    "cuestionario.",
  "Deja fuera las afirmaciones cuya nota de contexto no cumple las comprobaciones, las " +
    "repetidas y las que no separan a los partidos, porque todos " +
    `los que tienen posición coinciden, y no deja que un tema supere el 30${NBSP}% del ` +
    "cuestionario. Entre las demás, elige primero las que dan posición al partido que menos " +
    "tiene hasta ese momento; en caso de empate, las que muestran más posiciones distintas y, " +
    "después, las que se propusieron antes. Todos los partidos cuentan igual.",
  "El cuestionario tiene el mayor número de afirmaciones con el que todos los partidos tienen " +
    `posición en al menos el 50${NBSP}% de ellas. Si no es posible cumplir estas condiciones, ` +
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
    expect(document.title).toBe("Metodología · IdeologiApp");
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

  test("describes the Party-balanced agenda and orientation-level statements", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Cómo se redactan las afirmaciones" });
    const paragraphs = within(region)
      .getAllByText((_, element) => element?.tagName === "P")
      .map((p) => p.textContent);
    expect(paragraphs).toEqual(STATEMENTS_TEXTS);
    expect(screen.queryByText(/unas 30 afirmaciones/)).toBeNull();
    expect(screen.queryByText(/propuestas que traten varios programas/)).toBeNull();
  });

  test("says silence is no stance and a concrete proposal in either direction counts", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Cómo se sitúa a cada partido" });
    expect(within(region).getByText(POSITIONS_NO_STANCE_TEXT)).toBeTruthy();
  });

  test("says a slipped quote copy is replaced by the manifesto's exact text, never the stance", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Cómo se sitúa a cada partido" });
    expect(
      within(region).getByText(
        /Si esa copia tiene una pequeña errata o indica otra página del fragmento que leía, se guarda en su lugar el texto exacto del programa y su página; la posición no cambia\.$/,
      ),
    ).toBeTruthy();
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

  test("explains the three-option affinity rule: sides, 1/0, exclusions, Important and N de M", () => {
    renderMethodology();
    const section = screen.getByRole("region", { name: "Cómo se calcula la afinidad" });
    const text = (section.textContent ?? "").replace(/\s+/g, " ");
    for (const phrase of [
      "«De acuerdo», «En desacuerdo» o «Neutral / No lo sé»",
      "se lee por su lado",
      "cuenta como una coincidencia (1)",
      "no coincide (0)",
      "No cuentan las afirmaciones en las que respondes «Neutral / No lo sé»",
      "no tiene posición o tiene una posición neutral",
      "cuentan el doble",
      "hasta un tercio de las afirmaciones, redondeando hacia arriba",
      "la marca se quita, porque no contaría",
      "«N de M coincidencias»",
      "menos de 5 afirmaciones",
    ]) {
      expect(text).toContain(phrase);
    }
    expect(text).not.toMatch(/25 puntos|saltes|cinco puntos/);
    const positions = screen.getByRole("region", { name: "Cómo se sitúa a cada partido" });
    expect(positions.textContent).toContain("solo cuenta de qué lado está la posición");
  });

  test("lists the seven Validation checks with the default thresholds", () => {
    renderMethodology();
    const region = screen.getByRole("region", { name: "Comprobaciones antes de publicar" });
    const items = within(region).getAllByRole("listitem");
    expect(items).toHaveLength(7);
    expect(items[1]?.textContent).toBe(
      `cada partido tiene posición en al menos el 50${NBSP}% de las afirmaciones;`,
    );
    expect(items[4]?.textContent).toBe("el cuestionario tiene entre 25 y 35 afirmaciones;");
    expect(items[5]?.textContent).toBe(
      `ningún tema reúne más del 30${NBSP}% de las afirmaciones;`,
    );
    expect(items[6]?.textContent?.replace(/\s+/g, " ")).toBe(
      "cada afirmación tiene una nota de contexto de entre 30 y 300 caracteres que no usa " +
        "ninguna palabra valorativa de una lista fija.",
    );
    // pipeline-verified-findings: the threshold is 50 % (it was 60 %).
    const main = screen.getByRole("main").textContent ?? "";
    expect(main.split(`50${NBSP}%`)).toHaveLength(3);
    expect(main).not.toContain(`60${NBSP}%`);
  });

  test("states the privacy model and the disclaimer inside the Aviso card", () => {
    renderMethodology();
    const privacy = screen.getByRole("region", { name: "Tus respuestas" });
    expect(within(privacy).getByText(PRIVACY_TEXT)).toBeTruthy();
    expect(within(privacy).getByText(SHARE_TEXT)).toBeTruthy();
    // feedback-api: the third paragraph says what feedback stores.
    const paragraphs = Array.from(privacy.querySelectorAll("p")).map((p) => p.textContent);
    expect(paragraphs).toEqual([PRIVACY_TEXT, SHARE_TEXT, FEEDBACK_TEXT, LEGAL_LINK_TEXT]);
    // legal-privacy-page: the privacy section links to the legal page.
    expect(within(privacy).getByRole("link", { name: "Aviso legal y privacidad" }).getAttribute("href")).toBe(
      "/legal",
    );
    expect(privacy.textContent).not.toContain("se usará");
    const disclaimer = screen.getByRole("region", { name: "Aviso" });
    expect(disclaimer.className).toBe("card");
    expect(within(disclaimer).getByText(DISCLAIMER_TEXT)).toBeTruthy();
  });

  test("main links only to its own sections, the legal page and home, has no images and no request", () => {
    const fetch = renderMethodology();
    const main = screen.getByRole("main");
    const toc = within(main).getByRole("navigation", { name: "En esta página" });
    const tocLinks = within(toc).getAllByRole("link");
    expect(tocLinks).toHaveLength(HEADINGS.length);
    for (const link of tocLinks) {
      const target = main.querySelector(link.getAttribute("href")!);
      expect(target?.tagName).toBe("H2");
    }
    const links = within(main).getAllByRole("link").filter((link) => !toc.contains(link));
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Aviso legal y privacidad", "/legal"],
      ["Volver al inicio", "/"],
    ]);
    expect(main.querySelectorAll("img, svg")).toHaveLength(0);
    expect(apiPaths(fetch)).toEqual([]);
  });
});
