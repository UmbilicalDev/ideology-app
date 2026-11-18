// legal-privacy-page Scenarios 1-5, rendered through App at /legal. Fictitious
// holders and contact only: no real name, NIF, address or email.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, test, vi } from "vitest";

import { FEEDBACK_RETENTION_MONTHS, createPublicApiClient, type FetchLike } from "@ideology-app/core";

import { App } from "../../app/App";
import { apiPaths, jsonResponse, textResponse } from "../../test/fetch-mocks";
import { LEGAL_PATH } from "../paths";
import { LEGAL_LAST_UPDATED, LEGAL_TITLE } from "./LegalPage";

const CONFIGURED = {
  holders: [
    { name: "Persona Uno", nif: "00000000T" },
    { name: "Persona Dos", nif: "00000001R" },
  ],
  contact_email: "contacto@ideologiapp.test",
  address: "Calle Ficticia 1, 00000 Ciudad",
};
const EMPTY = { holders: [], contact_email: null, address: null };

const HEADINGS = ["Titulares y contacto", "Condiciones de uso", "Política de privacidad", "Cookies y almacenamiento"];

const HOLDERS_TEXT =
  "IdeologiApp es un proyecto de personas físicas, no de una empresa ni de una asociación. Sus " +
  "titulares, que lo gestionan conjuntamente y son corresponsables del tratamiento de los datos " +
  "descrito en esta página, son:";
const HOLDERS_PENDING = "Los nombres de los titulares están pendientes de publicación.";
const CONTACT_TEXT =
  "Contacto: contacto@ideologiapp.test. Escríbenos para cualquier consulta sobre esta página o " +
  "para ejercer tus derechos.";
const CONTACT_PENDING = "La dirección de contacto está pendiente de publicación.";

const TERMS_TEXTS = [
  "IdeologiApp no es una recomendación de voto. Las afirmaciones del cuestionario y las " +
    "posiciones de los partidos las genera automáticamente una inteligencia artificial a partir " +
    "de los programas electorales, sin revisión humana, y pueden contener errores. La afinidad " +
    "solo refleja lo que dicen los programas, no lo que los partidos han hecho o votado. Cómo se " +
    "generan y se comprueban se explica en Metodología y en Transparencia IA.",
  "Cada posición se respalda con una cita literal del programa electoral del partido, con su " +
    "página, reproducida con fines de análisis y comentario al amparo del derecho de cita " +
    "(artículo 32 de la Ley de Propiedad Intelectual). Los programas pertenecen a sus autores. " +
    "Los logotipos de los partidos se muestran solo para identificarlos: pertenecen a sus " +
    "titulares y su uso no implica relación con ellos ni su apoyo.",
];

const PRIVACY_TEXTS = [
  "Tus respuestas al cuestionario, las afirmaciones que marcas como importantes y tu resultado " +
    "no se envían a ningún servidor ni se guardan: la afinidad se calcula en tu navegador, así " +
    "que no tratamos tus opiniones políticas. Si compartes tu resultado, el enlace lleva tus " +
    "respuestas tras el símbolo «#», una parte de la dirección que los navegadores no envían al " +
    "servidor; quien tenga el enlace puede verlas.",
  "Las opiniones que nos envías con «Danos tu opinión», que es voluntario: guardamos solo el " +
    "texto, desde dónde la envías (el menú general o la pantalla de resultados), la fecha y, " +
    "cuando la revisamos, la fecha de revisión. No escribas en el mensaje datos personales ni " +
    "opiniones políticas, tuyas o de otras personas.",
  "Tu dirección IP, que, como en cualquier web, recibe el servidor para enviarte la página. No " +
    "guardamos registros de acceso. Al enviar una opinión, el servidor convierte tu dirección IP " +
    "en un código del que no se puede recuperar para limitar los envíos masivos; ese código se " +
    "guarda solo en la memoria del servidor, nunca en disco, y se descarta a partir de los 10 " +
    "minutos.",
  "Solo los titulares, a través de una página de administración protegida con contraseña. La " +
    "web se aloja en un servidor de Netcup GmbH en Alemania, que actúa como encargado del " +
    "tratamiento. Los datos no salen de la Unión Europea y no los cedemos a nadie, salvo " +
    "obligación legal. Si compartes IdeologiApp con los botones de otras redes o aplicaciones, " +
    "se abre el servicio que elijas, que trata tus datos según su propia política; solo se " +
    "comparte la dirección de IdeologiApp.",
  "Puedes pedirnos el acceso a tus datos, su rectificación o supresión, la limitación de su " +
    "tratamiento o su portabilidad, y oponerte a su tratamiento, escribiendo a la dirección de " +
    "contacto. Como no guardamos nada que te identifique, para localizar una opinión indícanos " +
    "su texto y la fecha aproximada de envío. También puedes reclamar ante la Agencia Española " +
    "de Protección de Datos en www.aepd.es.",
];

// Built from the constant: changing FEEDBACK_RETENTION_MONTHS changes the copy.
const RETENTION_TEXT =
  `Guardamos cada opinión un máximo de ${FEEDBACK_RETENTION_MONTHS} meses desde que la ` +
  "recibimos, y después la borramos, también de las copias de seguridad. Podemos borrarla antes.";

const COOKIE_TEXTS = [
  "Las páginas públicas de IdeologiApp no instalan cookies ni usan el almacenamiento de tu " +
    "navegador (almacenamiento local, de sesión o IndexedDB), y no cargan nada de otros sitios: " +
    "ni analítica, ni publicidad, ni fuentes, ni redes sociales. Tu navegador solo guarda en su " +
    "caché los archivos de la web, como en cualquier sitio, para cargarla más rápido.",
  "La única cookie es la de sesión de la página de administración, que solo reciben los " +
    "titulares al iniciar sesión. Es técnica e imprescindible para ese acceso, no se envía en " +
    "las páginas públicas y caduca al cerrar la sesión o el navegador, por lo que no requiere " +
    "consentimiento.",
  "Si algún día añadimos estadísticas u otras cookies que no sean técnicas, te pediremos antes " +
    "tu consentimiento y lo indicaremos aquí.",
];

function renderLegal(fetch: FetchLike) {
  render(
    <MemoryRouter initialEntries={[LEGAL_PATH]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
}

function fetchReturning(body: unknown) {
  return vi.fn<FetchLike>(async (url) => {
    if (url === "/api/v1/legal-notice") return jsonResponse(body);
    throw new Error(`unexpected request ${url}`);
  });
}

function region(name: string) {
  return screen.getByRole("region", { name });
}

function paragraphs(element: HTMLElement): string[] {
  return Array.from(element.querySelectorAll("p, li")).map((p) => p.textContent ?? "");
}

describe("LegalPage", () => {
  test("Scenario 1: the configured holders, NIFs, address and mailto link, from one request", async () => {
    const fetch = fetchReturning(CONFIGURED);
    renderLegal(fetch);
    const holders = region("Titulares y contacto");
    expect(within(holders).getByRole("status").textContent).toBe("Cargando los datos de los titulares…");

    const list = await within(holders).findByRole("list");
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Persona Uno, NIF 00000000T",
      "Persona Dos, NIF 00000001R",
    ]);
    expect(paragraphs(holders)).toEqual([
      HOLDERS_TEXT,
      "Persona Uno, NIF 00000000T",
      "Persona Dos, NIF 00000001R",
      "Dirección postal: Calle Ficticia 1, 00000 Ciudad",
      CONTACT_TEXT,
    ]);
    const mail = within(holders).getByRole("link", { name: "contacto@ideologiapp.test" });
    expect(mail.getAttribute("href")).toBe("mailto:contacto@ideologiapp.test");
    expect(within(holders).queryByRole("status")).toBeNull();
    expect(apiPaths(fetch)).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/legal-notice", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("Scenario 2: without NIF and address the holders show by name only", async () => {
    renderLegal(
      fetchReturning({
        holders: [
          { name: "Persona Uno", nif: null },
          { name: "Persona Dos", nif: null },
        ],
        contact_email: "contacto@ideologiapp.test",
        address: null,
      }),
    );
    const holders = region("Titulares y contacto");
    await within(holders).findByRole("list");
    expect(paragraphs(holders)).toEqual([HOLDERS_TEXT, "Persona Uno", "Persona Dos", CONTACT_TEXT]);
    expect(holders.textContent).not.toContain("NIF");
    expect(holders.textContent).not.toContain("Dirección postal");
  });

  test("Scenario 3: nothing configured shows the pending sentences and leaks nothing", async () => {
    renderLegal(fetchReturning(EMPTY));
    const holders = region("Titulares y contacto");
    expect(await within(holders).findByText(HOLDERS_PENDING)).toBeTruthy();
    expect(paragraphs(holders)).toEqual([HOLDERS_PENDING, CONTACT_PENDING]);
    expect(within(holders).queryByRole("list")).toBeNull();
    expect(within(holders).queryByRole("link")).toBeNull();
    const main = screen.getByRole("main");
    expect(main.querySelector('a[href^="mailto:"]')).toBeNull();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(HEADINGS);
    for (const word of ["undefined", "null", "TODO", "example", "Dirección postal"]) {
      expect(main.textContent).not.toContain(word);
    }
  });

  test.each<[string, () => ReturnType<FetchLike>]>([
    ["a 500", async () => textResponse(500)],
    ["a network error", async () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a broken contract", async () => jsonResponse({ holders: "Persona Uno" })],
  ])("Scenario 4: %s shows the alert; static sections stay; Reintentar requests again", async (_label, fail) => {
    const fetch = vi.fn<FetchLike>(fail);
    renderLegal(fetch);
    const holders = region("Titulares y contacto");
    const alert = await within(holders).findByRole("alert");
    expect(alert.textContent).toBe("No se han podido cargar los datos de los titulares y de contacto.");
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(HEADINGS);
    expect(within(region("Cookies y almacenamiento")).getByText(COOKIE_TEXTS[0]!)).toBeTruthy();

    fetch.mockImplementation(async () => jsonResponse(CONFIGURED));
    const retry = within(holders).getByRole("button", { name: "Reintentar" });
    expect(retry.className).toBe("button-primary");
    fireEvent.click(retry);
    expect(within(holders).getByRole("status").textContent).toBe("Cargando los datos de los titulares…");
    expect(await within(holders).findByRole("list")).toBeTruthy();
    expect(within(holders).queryByRole("alert")).toBeNull();
    expect(apiPaths(fetch)).toHaveLength(2);
    expect(apiPaths(fetch)).toEqual(["/api/v1/legal-notice", "/api/v1/legal-notice"]);
  });

  test("the h1 is focused, the tab title is set and restored on leaving", async () => {
    document.title = "IdeologiApp";
    renderLegal(fetchReturning(EMPTY));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Aviso legal y privacidad");
    expect(document.activeElement).toBe(h1);
    expect(document.title).toBe(LEGAL_TITLE);
    expect(LEGAL_TITLE).toBe("Aviso legal y privacidad · IdeologiApp");
    expect(screen.getByRole("banner").textContent).toBe("IdeologiApp/Aviso legal");
    await screen.findByText(HOLDERS_PENDING);

    fireEvent.click(screen.getByRole("link", { name: "Volver al inicio" }));
    expect(document.title).toBe("IdeologiApp");
  });

  test("the header has the lead and the last update; the index has four entries", async () => {
    renderLegal(fetchReturning(EMPTY));
    const main = screen.getByRole("main");
    expect(main.querySelector(".doc-page__lead")?.textContent).toBe(
      "Quién es responsable de IdeologiApp, en qué condiciones puedes usarla, qué datos tratamos y " +
        "qué se guarda en tu navegador.",
    );
    expect(main.querySelector(".doc-page__updated")?.textContent).toBe(
      `Última actualización: ${LEGAL_LAST_UPDATED}`,
    );
    const toc = within(main).getByRole("navigation", { name: "En esta página" });
    const entries = within(toc).getAllByRole("link");
    expect(entries.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Titulares y contacto", "#legal-holders-title"],
      ["Condiciones de uso", "#legal-terms-title"],
      ["Privacidad", "#legal-privacy-title"],
      ["Cookies", "#legal-cookies-title"],
    ]);
    for (const link of entries) {
      expect(main.querySelector(link.getAttribute("href")!)?.tagName).toBe("H2");
    }
    await screen.findByText(HOLDERS_PENDING);
  });

  test("four named sections in order, with the terms, privacy and cookie copy", async () => {
    renderLegal(fetchReturning(CONFIGURED));
    await screen.findByRole("link", { name: "contacto@ideologiapp.test" });
    const sections = Array.from(screen.getByRole("main").querySelectorAll("section"));
    expect(sections.map((s) => s.getAttribute("aria-labelledby"))).toEqual([
      "legal-holders-title",
      "legal-terms-title",
      "legal-privacy-title",
      "legal-cookies-title",
    ]);
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(HEADINGS);

    const terms = region("Condiciones de uso");
    const termParagraphs = paragraphs(terms);
    for (const text of TERMS_TEXTS) expect(termParagraphs).toContain(text);
    expect(within(terms).getByRole("link", { name: "Metodología" }).getAttribute("href")).toBe("/metodologia");
    expect(within(terms).getByRole("link", { name: "Transparencia IA" }).getAttribute("href")).toBe(
      "/transparencia",
    );

    const privacy = region("Política de privacidad");
    expect(within(privacy).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Responsables",
      "Tus respuestas no salen de tu dispositivo",
      "Qué datos tratamos",
      "Para qué y con qué base legal",
      "Cuánto tiempo los guardamos",
      "Quién más accede a los datos",
      "Tus derechos",
    ]);
    const privacyParagraphs = paragraphs(privacy);
    for (const text of PRIVACY_TEXTS) expect(privacyParagraphs).toContain(text);
    expect(within(privacy).getAllByRole("listitem")).toHaveLength(2);
    expect(within(privacy).getByRole("link", { name: "www.aepd.es" }).getAttribute("href")).toBe(
      "https://www.aepd.es/",
    );

    expect(paragraphs(region("Cookies y almacenamiento"))).toEqual(COOKIE_TEXTS);
  });

  test("the retention sentence is built from FEEDBACK_RETENTION_MONTHS", async () => {
    expect(FEEDBACK_RETENTION_MONTHS).toBe(12);
    renderLegal(fetchReturning(EMPTY));
    await screen.findByText(HOLDERS_PENDING);
    expect(paragraphs(region("Política de privacidad"))).toContain(RETENTION_TEXT);
  });

  test("no image, no /admin, and nothing that reads as a placeholder", async () => {
    renderLegal(fetchReturning(CONFIGURED));
    await screen.findByRole("link", { name: "contacto@ideologiapp.test" });
    const main = screen.getByRole("main");
    expect(main.querySelectorAll("img")).toHaveLength(0);
    for (const link of main.querySelectorAll("a")) {
      expect(link.getAttribute("href")).not.toContain("/admin");
    }
    for (const word of ["undefined", "null", "TODO", "example"]) {
      expect(main.textContent).not.toContain(word);
    }
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
  });
});

// donate-buymeacoffee Scenario 5: the donation copy shows only when the
// server has a donation link. Fictitious profile only.
describe("LegalPage donation copy", () => {
  const PROFILE = "https://www.buymeacoffee.com/perfil_de_prueba";
  const TERMS_DONATION =
    "Las donaciones son voluntarias: puedes usar IdeologiApp igual sin donar, y donar no cambia " +
    "las afirmaciones, las posiciones de los partidos ni ningún resultado. No aceptamos donaciones " +
    "hechas en nombre de partidos políticos. Si detectamos una donación hecha en nombre de un " +
    "partido político, la devolveremos.";
  const PRIVACY_DONATION = [
    "El enlace «Invítanos a un café» abre en una pestaña nueva la página del proyecto en Buy Me a " +
      "Coffee, un servicio de otra empresa. Es un enlace normal: IdeologiApp no carga nada de Buy " +
      "Me a Coffee, no registra si lo abres y no le envía tus respuestas ni la página desde la que " +
      "llegas.",
    "Si donas, lo haces en Buy Me a Coffee, con sus propias condiciones y su política de " +
      "privacidad, y es ese servicio el que trata tus datos de pago. Las donaciones las recibe uno " +
      "de los titulares en su cuenta de Buy Me a Coffee; de cada donación solo vemos lo que ese " +
      "servicio muestra a quien la recibe y lo usamos únicamente para gestionarla y agradecerla.",
  ];

  function withDonation(donation: unknown) {
    return vi.fn<FetchLike>(async (url) => {
      if (url === "/api/v1/legal-notice") return jsonResponse(CONFIGURED);
      if (url === "/api/v1/donation") return jsonResponse(donation);
      throw new Error(`unexpected request ${url}`);
    });
  }

  const squash = (texts: string[]) => texts.map((t) => t.replace(/\s+/g, " ").trim());

  test("configured: the terms paragraph and the Donaciones subsection, in place", async () => {
    renderLegal(withDonation({ url: PROFILE }));
    await screen.findByRole("heading", { level: 3, name: "Donaciones" });

    const terms = squash(paragraphs(region("Condiciones de uso")));
    const free = terms.findIndex((t) => t.startsWith("Puedes usar IdeologiApp gratis"));
    expect(terms[free + 1]).toBe(TERMS_DONATION);

    const privacy = region("Política de privacidad");
    expect(within(privacy).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Responsables",
      "Tus respuestas no salen de tu dispositivo",
      "Qué datos tratamos",
      "Para qué y con qué base legal",
      "Cuánto tiempo los guardamos",
      "Quién más accede a los datos",
      "Donaciones",
      "Tus derechos",
    ]);
    const heading = within(privacy).getByRole("heading", { level: 3, name: "Donaciones" });
    const following = [heading.nextElementSibling, heading.nextElementSibling?.nextElementSibling];
    expect(squash(following.map((el) => el?.textContent ?? ""))).toEqual(PRIVACY_DONATION);
    expect(following[1]?.nextElementSibling?.textContent).toBe("Tus derechos");
    // The copy names no holder, and no profile URL is printed.
    expect(screen.getByRole("main").textContent).not.toContain("buymeacoffee.com");
  });

  test.each([
    ["unset", { url: null }],
    ["a contract break", { url: "https://www.buymeacoffee.com/perfil?ref=x" }],
  ])("%s: no donation copy, and the rest of the page is unchanged", async (_name, donation) => {
    const fetch = withDonation(donation);
    renderLegal(fetch);
    await screen.findByRole("link", { name: "contacto@ideologiapp.test" });
    await vi.waitFor(() => expect(fetch.mock.calls.some(([u]) => u === "/api/v1/donation")).toBe(true));
    await Promise.resolve();
    const main = screen.getByRole("main");
    expect(within(main).queryByRole("heading", { name: "Donaciones" })).toBeNull();
    expect(main.textContent).not.toContain("donaci");
    expect(main.textContent).not.toContain("Buy Me a Coffee");
    for (const text of TERMS_TEXTS) expect(paragraphs(region("Condiciones de uso"))).toContain(text);
  });
});
