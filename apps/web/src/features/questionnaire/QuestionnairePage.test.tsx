import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, test, vi } from "vitest";

import {
  computeMatchScores,
  createPublicApiClient,
  type Answer,
  type FetchLike,
  type HttpResponseLike,
  type AnswerValue,
} from "@ideology-app/core";

import { App } from "../../app/App";
import {
  apiPaths,
  datasetVersionJson,
  electionJson,
  jsonResponse,
  partyLogoUrl,
  recordImageRequests,
  textResponse,
} from "../../test/fetch-mocks";
import {
  ANSWER_NAMES,
  answerAll,
  answerButton,
  findAnswerButtons,
  restartQuestionnaire,
  type AnswerName,
} from "../../test/questionnaire";
import { textWithoutLogos } from "../../test/text";
import { METHODOLOGY_PATH } from "../paths";
import { ANSWER_LOCK } from "./answer-lock";

const ELECTION_URL = "/api/v1/elections/1";
const VERSION_URL = "/api/v1/dataset-versions/1";

function routes(table: Record<string, () => HttpResponseLike>) {
  return vi.fn<FetchLike>(async (url) => {
    const respond = table[url];
    if (respond === undefined) {
      throw new Error(`unexpected request ${url}`);
    }
    return respond();
  });
}

function happyFetch(statements = 3) {
  return routes({
    [ELECTION_URL]: () => jsonResponse(electionJson()),
    [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements })),
  });
}

function renderAt(path: string, fetch: FetchLike) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createPublicApiClient({ fetch })} />
    </MemoryRouter>,
  );
}

async function openQuestionnaire(fetch: FetchLike = happyFetch()) {
  renderAt("/elecciones/1/cuestionario", fetch);
  await findAnswerButtons();
}

function heading2() {
  return screen.getByRole("heading", { level: 2 });
}

function button(name: string) {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

function toggle() {
  return button("Importante para mí");
}

function pressed() {
  return toggle().getAttribute("aria-pressed");
}

/** The polite status line of the Questionnaire (outside the step and end screen). */
function moveStatus() {
  return document.querySelector(".focus-shell__content [role='status'].visually-hidden")?.textContent;
}

const LOSS_NOTE = /Tus respuestas siguen solo en este navegador/;

describe("QuestionnairePage", () => {
  test("Scenario 1: loading, then the first Statement with three answer buttons and no Anterior", async () => {
    const fetch = happyFetch();
    renderAt("/elecciones/1/cuestionario", fetch);
    // Focus shell: no sidebar, only the brand and Salir.
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.getByRole("link", { name: "Salir" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Cuestionario");
    expect(screen.getByRole("status").textContent).toBe("Cargando cuestionario…");

    const group = await screen.findByRole("group", { name: "Afirmación de prueba 1" });
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Generales 2023");
    expect(h1.className).toBe("questionnaire__election");
    expect(screen.getByText("Afirmación 1 de 3")).toBeTruthy();
    const progress = screen.getByRole("progressbar", { name: "Afirmación 1 de 3" });
    expect(progress.getAttribute("value")).toBe("1");
    expect(progress.getAttribute("max")).toBe("3");

    const buttons = within(group).getAllByRole("button") as HTMLButtonElement[];
    expect(buttons.map((b) => b.textContent)).toEqual(["En desacuerdo", "Neutral / No lo sé", "De acuerdo"]);
    expect(buttons.map((b) => b.getAttribute("data-answer"))).toEqual(["-1", "neutral", "1"]);
    for (const [i, b] of buttons.entries()) {
      expect(within(group).getByRole("button", { name: ANSWER_NAMES[i] })).toBe(b);
      expect(b.type).toBe("button");
      expect(b.className).toBe("answer-button");
      expect(b.querySelector("svg.answer-button__icon")?.getAttribute("aria-hidden")).toBe("true");
    }
    // The Neutral button shows No lo sé on a smaller second line.
    expect(buttons[1]!.querySelector(".answer-button__sub")?.textContent).toBe("No lo sé");

    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button", { name: "Siguiente" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Saltar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Anterior" })).toBeNull();
    // The top row keeps its height with an empty placeholder.
    expect(document.querySelector(".statement-card__top .step-back-placeholder")).toBeTruthy();
    expect(screen.getByText(/Tus respuestas se quedan en este navegador/).className).toBe(
      "questionnaire__note",
    );
    // Initial load does not move focus; the status line is empty.
    expect(document.activeElement).toBe(document.body);
    expect(moveStatus()).toBe("");
    expect(apiPaths(fetch)).toEqual([ELECTION_URL, VERSION_URL]);
  });

  test("Scenarios 1-3: each tap answers and advances, and the last one reaches the end screen", async () => {
    const fetch = happyFetch();
    await openQuestionnaire(fetch);

    // Scenario 1.
    fireEvent.click(answerButton("De acuerdo"));
    expect(heading2().textContent).toBe("Afirmación de prueba 2");
    expect(screen.getByText("Afirmación 2 de 3")).toBeTruthy();
    expect(document.activeElement).toBe(heading2());
    expect(heading2().getAttribute("aria-describedby")).toBe("questionnaire-progress");
    expect(moveStatus()).toBe("Respuesta guardada: De acuerdo.");
    // No button looks chosen on the new Statement: the three are identical.
    expect(
      Array.from(document.querySelectorAll(".answer-button"), (b) => [b.className, b.getAttribute("aria-pressed")]),
    ).toEqual([
      ["answer-button", null],
      ["answer-button", null],
      ["answer-button", null],
    ]);

    // Scenario 2.
    fireEvent.click(answerButton("Neutral / No lo sé"));
    expect(heading2().textContent).toBe("Afirmación de prueba 3");
    expect(document.activeElement).toBe(heading2());
    expect(moveStatus()).toBe("Respuesta guardada: Neutral / No lo sé.");

    // Scenario 3.
    fireEvent.click(answerButton("En desacuerdo"));
    expect(heading2().textContent).toBe("Tus resultados");
    expect(document.activeElement).toBe(heading2());
    expect(moveStatus()).toBe("Respuesta guardada: En desacuerdo.");
    expect(screen.getByText("Muestra evaluada: 2/3 afirmaciones con opinión")).toBeTruthy();
    expect(screen.getByText("Has respondido «Neutral / No lo sé» en 1 afirmación.")).toBeTruthy();
    expect(screen.queryByText(/muy pronto/)).toBeNull();
    expect(document.querySelector(".answer-controls")).toBeNull();
    expect(screen.queryByRole("link", { name: "Volver al inicio" })).toBeNull();
    expect(screen.getByRole("link", { name: "IdeologiApp, ir al inicio" }).getAttribute("href")).toBe("/");

    // Only the two loads, and nothing stored.
    expect(apiPaths(fetch)).toEqual([ELECTION_URL, VERSION_URL]);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  test("a one-Statement questionnaire goes straight to the end screen", async () => {
    await openQuestionnaire(happyFetch(1));
    expect(screen.getByText("Afirmación 1 de 1")).toBeTruthy();
    fireEvent.click(answerButton("En desacuerdo"));
    expect(screen.getByText("Muestra evaluada: 1/1 afirmaciones con opinión")).toBeTruthy();
    expect(screen.getByText("No has respondido «Neutral / No lo sé» en ninguna afirmación.")).toBeTruthy();
  });

  test("Scenario 4: Anterior goes back and clears that Answer, keeping its flag", async () => {
    await openQuestionnaire();
    fireEvent.click(answerButton("De acuerdo"));
    // Anterior is in the top row from Statement 2 on, before the progress label.
    const back = button("Anterior");
    expect(back.className).toBe("step-back");
    expect(back.closest(".statement-card__top")?.lastElementChild?.id).toBe("questionnaire-progress");
    expect(back.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(document.querySelector(".step-back-placeholder")).toBeNull();

    fireEvent.click(toggle());
    fireEvent.click(answerButton("Neutral / No lo sé"));
    expect(heading2().textContent).toBe("Afirmación de prueba 3");
    // Neutral dropped Statement 2's flag (Decision 3).

    fireEvent.click(button("Anterior"));
    expect(heading2().textContent).toBe("Afirmación de prueba 2");
    expect(document.activeElement).toBe(heading2());
    expect(moveStatus()).toBe("Respuesta borrada. Vuelve a responder esta afirmación.");
    expect(pressed()).toBe("false");

    // Press the flag, go back again, and come forward: it is still pressed.
    fireEvent.click(toggle());
    fireEvent.click(button("Anterior"));
    expect(heading2().textContent).toBe("Afirmación de prueba 1");
    expect(screen.queryByRole("button", { name: "Anterior" })).toBeNull();
    expect(pressed()).toBe("false");
    fireEvent.click(answerButton("En desacuerdo"));
    expect(heading2().textContent).toBe("Afirmación de prueba 2");
    expect(pressed()).toBe("true");
    fireEvent.click(answerButton("De acuerdo"));
    fireEvent.click(answerButton("De acuerdo"));

    // Re-answered: 1 En desacuerdo, 2 De acuerdo (Important), 3 De acuerdo.
    expect(screen.getByText("Muestra evaluada: 3/3 afirmaciones con opinión")).toBeTruthy();
    expect(screen.getByText("No has respondido «Neutral / No lo sé» en ninguna afirmación.")).toBeTruthy();
    expect(screen.getByText("Has marcado 1 afirmación como importante.")).toBeTruthy();
  });

  test("Scenario 10: Tab order is Anterior, Importante para mí, then the three answers", async () => {
    await openQuestionnaire();
    fireEvent.click(answerButton("Neutral / No lo sé"));
    const card = document.querySelector(".statement-card")!;
    const tabbable = Array.from(card.querySelectorAll<HTMLElement>("button, [tabindex]")).filter(
      (element) => element.tabIndex >= 0,
    );
    expect(tabbable.map((element) => element.textContent)).toEqual([
      "Anterior",
      "Importante para mí",
      "En desacuerdo",
      "Neutral / No lo sé",
      "De acuerdo",
    ]);
    // The heading holds focus after a move but is not a Tab stop of its own.
    expect(heading2().tabIndex).toBe(-1);
  });

  test("Scenario 9: a double tap answers one Statement; a tap after the lock answers the next", async () => {
    await openQuestionnaire(happyFetch(6));
    answerAll([1, 1, 1]);
    expect(heading2().textContent).toBe("Afirmación de prueba 4");

    ANSWER_LOCK.ms = 300;
    // Times relative to now, after the unlocked taps above.
    const t0 = performance.now() + 1000;
    let now = t0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    fireEvent.click(answerButton("De acuerdo"));
    now = t0 + 150;
    fireEvent.click(answerButton("De acuerdo"));
    expect(heading2().textContent).toBe("Afirmación de prueba 5");
    // Anterior is locked too.
    fireEvent.click(button("Anterior"));
    expect(heading2().textContent).toBe("Afirmación de prueba 5");

    now = t0 + 400;
    fireEvent.click(answerButton("En desacuerdo"));
    expect(heading2().textContent).toBe("Afirmación de prueba 6");
    now = t0 + 800;
    fireEvent.click(button("Anterior"));
    expect(heading2().textContent).toBe("Afirmación de prueba 5");
    now = t0 + 1200;
    fireEvent.click(answerButton("Neutral / No lo sé"));
    fireEvent.click(answerButton("Neutral / No lo sé"));
    now = t0 + 1600;
    fireEvent.click(answerButton("De acuerdo"));
    // 1-4 De acuerdo, 5 Neutral, 6 De acuerdo.
    expect(heading2().textContent).toBe("Tus resultados");
    expect(screen.getByText("Muestra evaluada: 5/6 afirmaciones con opinión")).toBeTruthy();
  });

  test("the Statement slides in the way the Voter moved; the bar and the answer row are kept", async () => {
    await openQuestionnaire();
    const step = () => document.querySelector(".statement-step")!;
    const progress = document.querySelector("progress");
    const answers = document.querySelector(".answer-controls");
    // No transition on the initial load; only the Statement and Important row slide.
    expect(step().hasAttribute("data-enter")).toBe(false);
    expect(step().contains(toggle())).toBe(true);
    expect(step().contains(answers)).toBe(false);
    fireEvent.click(answerButton("Neutral / No lo sé"));
    expect(step().getAttribute("data-enter")).toBe("forward");
    fireEvent.click(answerButton("De acuerdo"));
    expect(step().getAttribute("data-enter")).toBe("forward");
    const third = step();
    fireEvent.click(button("Anterior"));
    expect(step().getAttribute("data-enter")).toBe("back");
    // A new block per Statement (so the animation replays), the same bar and buttons.
    expect(step()).not.toBe(third);
    expect(document.querySelector("progress")).toBe(progress);
    expect(document.querySelector(".answer-controls")).toBe(answers);

    answerAll([1, 1]);
    restartQuestionnaire();
    expect(step().hasAttribute("data-enter")).toBe(false);
  });

  test("the AI/privacy disclosure card follows the answer buttons and is absent on the end screen", async () => {
    await openQuestionnaire();
    const disclosure = screen.getByRole("region", {
      name: "Transparencia algorítmica y privacidad garantizada",
    });
    const title = within(disclosure).getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Transparencia algorítmica y privacidad garantizada");
    const note = within(disclosure).getByText(/Tus respuestas se quedan en este navegador/);
    expect(note.tagName).toBe("P");
    expect(note.className).toBe("questionnaire__note");
    expect(note.textContent).toBe(
      "Las afirmaciones las ha generado una inteligencia artificial a partir de los programas " +
        "electorales. Tus respuestas se quedan en este navegador: no se envían a ningún servidor y " +
        "se pierden si recargas o sales de la página.",
    );
    const icons = disclosure.querySelectorAll("svg");
    expect(icons).toHaveLength(1);
    expect(icons[0]?.getAttribute("aria-hidden")).toBe("true");
    const group = screen.getByRole("group", { name: "Afirmación de prueba 1" });
    expect(group.compareDocumentPosition(disclosure) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    answerAll(["neutral", "neutral", "neutral"]);
    expect(heading2().textContent).toBe("Tus resultados");
    expect(
      screen.queryByRole("region", { name: "Transparencia algorítmica y privacidad garantizada" }),
    ).toBeNull();
  });

  describe("Important flag", () => {
    test("the toggle flips on and off without advancing; focus stays on it; the hint names the cap", async () => {
      await openQuestionnaire();
      const star = toggle();
      expect(star.type).toBe("button");
      expect(pressed()).toBe("false");
      expect(star.hasAttribute("aria-disabled")).toBe(false);
      const hint = document.getElementById(star.getAttribute("aria-describedby") ?? "");
      expect(hint?.textContent).toBe(
        "Las afirmaciones importantes cuentan el doble al calcular la afinidad. Puedes marcar hasta 1.",
      );
      // A tooltip on hover or keyboard focus (CSS), always the description.
      expect(hint?.className).toBe("questionnaire__hint important-hint");
      expect(hint?.getAttribute("role")).toBe("tooltip");
      expect(star.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
      // The toggle follows the heading and comes before the answer buttons.
      const group = screen.getByRole("group", { name: "Afirmación de prueba 1" });
      expect(heading2().compareDocumentPosition(star) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(star.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

      star.focus();
      fireEvent.click(star);
      expect(pressed()).toBe("true");
      expect(star.classList.contains("important-toggle--flash")).toBe(true);
      expect(toggle().textContent).toBe("Importante para mí");
      expect(document.activeElement).toBe(toggle());
      expect(heading2().textContent).toBe("Afirmación de prueba 1");

      fireEvent.click(toggle());
      expect(pressed()).toBe("false");
      expect(star.classList.contains("important-toggle--flash")).toBe(false);
      expect(document.activeElement).toBe(toggle());
    });

    test("Escape dismisses the Important tooltip until the toggle is pointed at or focused again", async () => {
      await openQuestionnaire();
      const hint = document.getElementById("important-hint")!;
      act(() => toggle().focus());
      expect(hint.classList.contains("important-hint--dismissed")).toBe(false);
      fireEvent.keyDown(document, { key: "Escape" });
      expect(hint.classList.contains("important-hint--dismissed")).toBe(true);
      // The tooltip stays the toggle's description while hidden.
      expect(toggle().getAttribute("aria-describedby")).toContain("important-hint");

      act(() => {
        toggle().blur();
        toggle().focus();
      });
      expect(hint.classList.contains("important-hint--dismissed")).toBe(false);
      fireEvent.keyDown(document, { key: "Escape" });
      fireEvent.pointerOver(toggle());
      expect(hint.classList.contains("important-hint--dismissed")).toBe(false);
    });

    test("under reduced motion turning Important on sets no glow class", async () => {
      vi.stubGlobal(
        "matchMedia",
        (query: string) =>
          ({
            matches: query === "(prefers-reduced-motion: reduce)",
            media: query,
            addEventListener: () => {},
            removeEventListener: () => {},
          }) as unknown as MediaQueryList,
      );
      await openQuestionnaire();
      fireEvent.click(toggle());
      expect(pressed()).toBe("true");
      expect(toggle().classList.contains("important-toggle--flash")).toBe(false);
    });

    test("Scenario 5: at the cap the toggle is aria-disabled, says why, and an already marked one can be unpressed", async () => {
      await openQuestionnaire(happyFetch(32));
      const HINT =
        "Las afirmaciones importantes cuentan el doble al calcular la afinidad. Puedes marcar hasta 11.";
      const CAP =
        "Ya has marcado 11 afirmaciones como importantes, el máximo (un tercio del cuestionario).";
      expect(document.getElementById("important-hint")?.textContent).toBe(HINT);
      // Mark 11 of the first 19 Statements (1, 3, 5... 19 and 18), each before answering.
      for (let i = 1; i <= 19; i += 1) {
        expect(heading2().textContent).toBe(`Afirmación de prueba ${i}`);
        if (i % 2 === 1 || i === 18) fireEvent.click(toggle());
        fireEvent.click(answerButton("De acuerdo"));
      }
      expect(heading2().textContent).toBe("Afirmación de prueba 20");
      const star = toggle();
      expect(star.getAttribute("aria-disabled")).toBe("true");
      expect(pressed()).toBe("false");
      expect(star.disabled).toBe(false);
      expect(star.getAttribute("aria-describedby")).toBe("important-hint important-cap");
      const cap = document.getElementById("important-cap");
      expect(cap?.textContent).toBe(CAP);
      expect(cap?.className).toBe("important-cap");
      star.focus();
      fireEvent.click(star);
      expect(pressed()).toBe("false");
      expect(star.classList.contains("important-toggle--flash")).toBe(false);
      expect(document.activeElement).toBe(star);

      // Back to Statement 19 (marked): the toggle stays enabled and can be unpressed.
      fireEvent.click(button("Anterior"));
      expect(heading2().textContent).toBe("Afirmación de prueba 19");
      expect(pressed()).toBe("true");
      expect(toggle().hasAttribute("aria-disabled")).toBe(false);
      expect(document.getElementById("important-cap")).toBeNull();
      fireEvent.click(toggle());
      expect(pressed()).toBe("false");
      fireEvent.click(answerButton("De acuerdo"));
      // A slot is free again on Statement 20.
      expect(toggle().hasAttribute("aria-disabled")).toBe(false);
      fireEvent.click(toggle());
      expect(pressed()).toBe("true");
      fireEvent.click(answerButton("De acuerdo"));
      expect(toggle().getAttribute("aria-disabled")).toBe("true");
    });

    test("Scenario 5: the cap message is singular when the cap is 1", async () => {
      await openQuestionnaire();
      fireEvent.click(toggle());
      fireEvent.click(answerButton("De acuerdo"));
      expect(document.getElementById("important-cap")?.textContent).toBe(
        "Ya has marcado 1 afirmación como importante, el máximo (un tercio del cuestionario).",
      );
    });

    test("Scenario 6: Neutral on the last free slot drops the flag and frees it", async () => {
      await openQuestionnaire(happyFetch(32));
      for (let i = 1; i <= 10; i += 1) {
        fireEvent.click(toggle());
        fireEvent.click(answerButton("De acuerdo"));
      }
      fireEvent.click(toggle());
      expect(pressed()).toBe("true");
      fireEvent.click(answerButton("Neutral / No lo sé"));
      expect(heading2().textContent).toBe("Afirmación de prueba 12");
      expect(toggle().hasAttribute("aria-disabled")).toBe(false);
      answerAll(Array.from({ length: 21 }, () => -1 as const));
      expect(screen.getByText("Has marcado 10 afirmaciones como importantes.")).toBeTruthy();
    });

    test("the end screen counts sided Important Statements, and nothing leaves the page", async () => {
      const fetch = happyFetch(6);
      await openQuestionnaire(fetch);
      answerAll([{ value: 1, important: true }, { value: -1, important: true }, "neutral", 1, 1, 1]);
      const summary = screen.getByRole("region", { name: "Muestra evaluada: 5/6 afirmaciones con opinión" });
      expect(within(summary).getByText("Has respondido «Neutral / No lo sé» en 1 afirmación.")).toBeTruthy();
      const sentence = within(summary).getByText("Has marcado 2 afirmaciones como importantes.");
      expect(sentence.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
      expect(sentence.getAttribute("data-marked")).toBe("true");
      const donut = summary.querySelector(".summary-donut")!;
      expect(donut.getAttribute("aria-hidden")).toBe("true");
      expect(donut.textContent).toBe("83 %");

      expect(apiPaths(fetch)).toEqual([ELECTION_URL, VERSION_URL]);
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
      expect(document.cookie).toBe("");
    });
  });

  describe("Repetir cuestionario", () => {
    const TEXT =
      "Se borrarán tus respuestas y el resultado. Copia antes el enlace si quieres guardarlo.";

    async function reachEnd() {
      await openQuestionnaire();
      answerAll([{ value: 1, important: true }, "neutral", -1]);
      expect(heading2().textContent).toBe("Tus resultados");
      return {
        summary: screen.getByText(/^Muestra evaluada:/).textContent,
        ranking: textWithoutLogos(screen.getByRole("list", { name: "Tus resultados" })),
      };
    }

    function openDialog() {
      fireEvent.click(button("Repetir cuestionario"));
      return screen.getByRole("dialog", { name: "¿Repetir el cuestionario?" });
    }

    test("Scenario 7: the dialog asks first; Sí, repetir starts over from Statement 1", async () => {
      await reachEnd();
      const dialog = openDialog();
      expect(dialog.tagName).toBe("DIALOG");
      expect(dialog.hasAttribute("open")).toBe(true);
      expect(document.getElementById(dialog.getAttribute("aria-describedby")!)?.textContent).toBe(TEXT);
      const buttons = within(dialog).getAllByRole("button");
      expect(buttons.map((b) => [b.textContent, b.className])).toEqual([
        ["Cancelar", "button-secondary"],
        ["Sí, repetir", "button-primary"],
      ]);
      expect(document.activeElement).toBe(buttons[0]);

      fireEvent.click(buttons[1]!);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(document.activeElement).toBe(heading2());
      expect(moveStatus()).toBe("Cuestionario reiniciado.");
      expect(pressed()).toBe("false");
      expect(screen.queryByRole("button", { name: "Anterior" })).toBeNull();
      expect(screen.getByText("Afirmación 1 de 3")).toBeTruthy();
      // No Answers and no flags: answering everything Neutral gives 0/3 and no marks.
      answerAll(["neutral", "neutral", "neutral"]);
      expect(screen.getByText("Muestra evaluada: 0/3 afirmaciones con opinión")).toBeTruthy();
      expect(screen.getByText("No has marcado ninguna afirmación como importante.")).toBeTruthy();
    });

    test.each<[string, (dialog: HTMLElement) => void]>([
      ["Cancelar", (dialog) => fireEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }))],
      ["Escape", (dialog) => fireEvent(dialog, new Event("cancel", { cancelable: true }))],
      [
        "a backdrop click",
        (dialog) => {
          fireEvent.pointerDown(dialog);
          fireEvent.click(dialog);
        },
      ],
    ])("Scenario 7b: %s closes it with the result unchanged and focus on the button", async (_label, cancel) => {
      const before = await reachEnd();
      const dialog = openDialog();
      cancel(dialog);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(heading2().textContent).toBe("Tus resultados");
      expect(document.activeElement).toBe(button("Repetir cuestionario"));
      expect({
        summary: screen.getByText(/^Muestra evaluada:/).textContent,
        ranking: textWithoutLogos(screen.getByRole("list", { name: "Tus resultados" })),
      }).toEqual(before);
      expect(screen.getByRole("button", { name: "Copiar enlace" })).toBeTruthy();
    });

    test("Scenario 7b: a click inside the surface does not close it", async () => {
      await reachEnd();
      const dialog = openDialog();
      const text = screen.getByText(TEXT);
      fireEvent.pointerDown(text);
      fireEvent.click(text);
      expect(screen.getByRole("dialog")).toBe(dialog);
    });

    test("Scenario 7b: Tab cycles between Cancelar and Sí, repetir", async () => {
      await reachEnd();
      const dialog = openDialog();
      const [cancel, confirm] = within(dialog).getAllByRole("button");
      expect(document.activeElement).toBe(cancel);
      fireEvent.keyDown(dialog, { key: "Tab" });
      expect(document.activeElement).toBe(confirm);
      fireEvent.keyDown(dialog, { key: "Tab" });
      expect(document.activeElement).toBe(cancel);
      fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
      expect(document.activeElement).toBe(confirm);
      fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
      expect(document.activeElement).toBe(cancel);
    });
  });

  test("Scenario 7: no Published version shows not available after one request", async () => {
    const fetch = routes({
      "/api/v1/elections/2": () =>
        jsonResponse(electionJson({ id: 2, status: "draft", published_dataset_version_id: null })),
    });
    renderAt("/elecciones/2/cuestionario", fetch);
    expect(
      await screen.findByText(
        "El cuestionario de estas elecciones todavía no está disponible. Vuelve a consultarlo más adelante.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" }).getAttribute("href")).toBe("/");
    expect(apiPaths(fetch)).toHaveLength(1);
  });

  test("Scenario 7: a version with zero Statements shows not available", async () => {
    const fetch = routes({
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 0 })),
    });
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(await screen.findByText(/todavía no está disponible/)).toBeTruthy();
    expect(document.querySelector(".answer-controls")).toBeNull();
  });

  test("Scenario 7: an unknown Election renders Página no encontrada", async () => {
    const fetch = routes({
      "/api/v1/elections/999": () => jsonResponse({ error: { code: "election_not_found" } }, 404),
    });
    renderAt("/elecciones/999/cuestionario", fetch);
    expect(
      (await screen.findByRole("heading", { level: 1, name: "Página no encontrada" })).textContent,
    ).toBe("Página no encontrada");
    expect(apiPaths(fetch)).toHaveLength(1);
  });

  test("Scenario 7: an API error shows the alert, and Reintentar loads again", async () => {
    let fail = true;
    const fetch = routes({
      [ELECTION_URL]: () => (fail ? textResponse(500) : jsonResponse(electionJson())),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 3 })),
    });
    const consoleError = vi.spyOn(console, "error");
    renderAt("/elecciones/1/cuestionario", fetch);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(
      "No se ha podido cargar el cuestionario. Comprueba tu conexión e inténtalo de nuevo.",
    )).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver al inicio" })).toBeTruthy();

    fail = false;
    fireEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(screen.getByRole("status").textContent).toBe("Cargando cuestionario…");
    expect(await screen.findByRole("group", { name: "Afirmación de prueba 1" })).toBeTruthy();
    expect(apiPaths(fetch)).toEqual([ELECTION_URL, ELECTION_URL, VERSION_URL]);
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  test.each<[string, () => HttpResponseLike]>([
    ["a 404 from the Dataset Version", () => jsonResponse({ error: {} }, 404)],
    ["a Dataset Version of another Election", () => jsonResponse(datasetVersionJson({ statements: 3, electionId: 5 }))],
    ["an invalid Dataset Version body", () => jsonResponse({ id: 1 })],
  ])("Scenario 7: %s shows the error alert", async (_label, version) => {
    const fetch = routes({
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: version,
    });
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Página no encontrada")).toBeNull();
  });

  test("Scenario 7: a network failure shows the error alert", async () => {
    const fetch = vi.fn<FetchLike>(async () => {
      throw new TypeError("Failed to fetch");
    });
    renderAt("/elecciones/1/cuestionario", fetch);
    expect(await screen.findByRole("button", { name: "Reintentar" })).toBeTruthy();
  });

  test("the Election's published version id is the one requested", async () => {
    const fetch = routes({
      "/api/v1/elections/4": () => jsonResponse(electionJson({ id: 4, published_dataset_version_id: 9 })),
      "/api/v1/dataset-versions/9": () =>
        jsonResponse(datasetVersionJson({ statements: 2, electionId: 4, id: 9 })),
    });
    renderAt("/elecciones/4/cuestionario", fetch);
    expect(await screen.findByText("Afirmación 1 de 2")).toBeTruthy();
  });

  test("Party logos are preloaded in Party order before the first Answer, never in ranking order", async () => {
    const { srcs } = recordImageRequests();
    const fetch = routes({
      [ELECTION_URL]: () => jsonResponse(electionJson()),
      [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 3, logos: true })),
    });
    await openQuestionnaire(fetch);
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(2)]);
    expect(document.querySelector(".party-logo")).toBeNull();

    // Disagreeing with everything ranks Partido Dos first.
    answerAll([-1, -1, -1]);
    const ranking = Array.from(document.querySelectorAll(".ranking-row img"), (img) =>
      img.getAttribute("src"),
    );
    expect(ranking).toEqual([partyLogoUrl(2), partyLogoUrl(1)]);
    expect(srcs).toEqual([partyLogoUrl(1), partyLogoUrl(2)]);
    expect(apiPaths(fetch)).toEqual([ELECTION_URL, VERSION_URL]);
  });

  describe("results", () => {
    const NBSP = " ";
    const LEGEND =
      "Se pueden comparar menos de 5 afirmaciones con este partido, así que su afinidad se basa " +
      "en pocos datos.";
    const PROMPT =
      "Todavía no se puede calcular tu afinidad: no has respondido con opinión ninguna afirmación " +
      "en la que los partidos tengan posición. Pulsa «Repetir cuestionario» y responde al menos " +
      "una con «De acuerdo» o «En desacuerdo».";
    // The fixture's Party Positions (datasetVersionJson, 6 Statements, ids 101..106).
    const IDS = [101, 102, 103, 104, 105, 106];
    const PARTIES = [
      { partyId: "Uno", positions: IDS.map((statementId) => ({ statementId, value: 1 as const })) },
      {
        partyId: "Dos",
        positions: IDS.map((statementId, i) => ({
          statementId,
          value: i === 0 ? ("no_stance" as const) : (-1 as const),
        })),
      },
    ];

    let currentUrl = "";
    function LocationProbe() {
      const location = useLocation();
      currentUrl = `${location.pathname}${location.search}${location.hash}`;
      return null;
    }

    function renderResults(fetch: FetchLike) {
      return render(
        <MemoryRouter initialEntries={["/elecciones/1/cuestionario"]}>
          <App api={createPublicApiClient({ fetch })} />
          <LocationProbe />
        </MemoryRouter>,
      );
    }

    async function openSix(fetch: FetchLike = happyFetch(6)) {
      const view = renderResults(fetch);
      await findAnswerButtons();
      return view;
    }

    type Step = { readonly label: AnswerName; readonly important?: boolean } | "neutral";

    function walk(steps: readonly Step[]) {
      for (const step of steps) {
        if (step === "neutral") {
          fireEvent.click(answerButton("Neutral / No lo sé"));
          continue;
        }
        if (step.important === true) {
          fireEvent.click(button("Importante para mí"));
        }
        fireEvent.click(answerButton(step.label));
      }
    }

    function rankingRows() {
      return within(screen.getByRole("list", { name: "Tus resultados" })).getAllByRole("listitem");
    }

    function rowTexts() {
      return rankingRows().map(textWithoutLogos);
    }

    function enginePercent(answers: readonly Answer[]) {
      return computeMatchScores(answers, PARTIES).map((r) => [
        r.partyId,
        r.matchScore === null ? null : Math.round(r.matchScore * 100),
      ]);
    }

    function engineAnswers(values: readonly AnswerValue[], important: readonly number[] = []) {
      return values.map((value, i) => ({
        statementId: IDS[i]!,
        value,
        important: important.includes(IDS[i]!),
      }));
    }

    const AGREE = { label: "De acuerdo" } as const;

    test("Scenario 1: ranking ordered by score, focus on Tus resultados, badge and legend", async () => {
      const fetch = happyFetch(6);
      await openSix(fetch);
      walk([AGREE, AGREE, AGREE, AGREE, AGREE, "neutral"]);

      expect(heading2().textContent).toBe("Tus resultados");
      expect(document.activeElement).toBe(heading2());
      expect(screen.getByText("Muestra evaluada: 5/6 afirmaciones con opinión")).toBeTruthy();
      expect(
        screen.getByText("Afinidad entre tus respuestas y el programa de cada partido, de mayor a menor."),
      ).toBeTruthy();
      expect(rowTexts()).toEqual([
        `Partido Uno P1 100${NBSP}%5 de 5 coincidencias`,
        `Partido Dos P2 0${NBSP}%0 de 4 coincidencias Baja cobertura${LEGEND}`,
      ]);
      const chip = within(rankingRows()[1]!).getByRole("button", { name: "Baja cobertura" });
      expect(chip.className).toBe("coverage-badge");
      // The explanation is the chip's tooltip, not a legend under the ranking.
      expect(document.getElementById(chip.getAttribute("aria-describedby")!)?.textContent).toBe(LEGEND);
      expect(screen.getAllByText(LEGEND)).toHaveLength(1);
      expect(screen.getAllByText(LEGEND)[0]!.getAttribute("role")).toBe("tooltip");
      for (const li of rankingRows()) {
        expect(li.querySelector(".ranking-bar")?.getAttribute("aria-hidden")).toBe("true");
      }
      expect(enginePercent(engineAnswers([1, 1, 1, 1, 1, "neutral"]))).toEqual([
        ["Uno", 100],
        ["Dos", 0],
      ]);
      expect(screen.queryByText(PROMPT)).toBeNull();
      expect(screen.queryByRole("button", { name: "Revisar mis respuestas" })).toBeNull();
      const restart = button("Repetir cuestionario");
      expect(restart.className).toBe("button-primary");
      expect(restart.getAttribute("aria-haspopup")).toBe("dialog");
      // Repetir sits right after the summary, before the ranking and the share card.
      const summary = screen.getByText(/^Muestra evaluada:/).closest(".results-dashboard > *");
      expect(summary?.nextElementSibling).toBe(restart.parentElement);
      expect(screen.queryByRole("button", { name: "Volver a la última afirmación" })).toBeNull();
      // The warning is no longer a card: an alert button at the top right of
      // the ranking shows it inside the ranking card.
      const ranking = screen.getByRole("region", { name: "Afinidad por partido" });
      const warning = within(ranking).getByText(
        "Esto no es una recomendación de voto: solo compara tus respuestas con lo que dicen los " +
          "programas, según una inteligencia artificial que puede equivocarse.",
      );
      expect(warning.hidden).toBe(true);
      expect(document.querySelector(".notice-card")).toBeNull();
      const alert = within(ranking).getByRole("button", { name: "Aviso sobre estos resultados" });
      expect(alert.getAttribute("aria-controls")).toBe(warning.id);
      expect(alert.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(alert);
      expect([alert.getAttribute("aria-expanded"), warning.hidden]).toEqual(["true", false]);
      fireEvent.click(alert);
      expect(warning.hidden).toBe(true);
      // No loss note and no home button: `Salir` and the brand in the top bar go home.
      expect(screen.queryByText(LOSS_NOTE)).toBeNull();
      expect(screen.queryByRole("link", { name: "Volver al inicio" })).toBeNull();
      expect(screen.queryByRole("link", { name: "Ir al inicio" })).toBeNull();
      expect(button("Repetir cuestionario").nextElementSibling).toBeNull();
      expect(screen.getByRole("region", { name: "Comprueba de dónde salen tus coincidencias" })).toBeTruthy();
    });

    test("Scenario 2: a tie on the displayed percentage is ordered by name", async () => {
      await openSix();
      const disagree = { label: "En desacuerdo" } as const;
      walk(["neutral", "neutral", AGREE, AGREE, disagree, disagree]);
      expect(rowTexts()).toEqual([
        `Partido Dos P2 50${NBSP}%2 de 4 coincidencias Baja cobertura${LEGEND}`,
        `Partido Uno P1 50${NBSP}%2 de 4 coincidencias Baja cobertura${LEGEND}`,
      ]);
      expect(enginePercent(engineAnswers(["neutral", "neutral", 1, 1, -1, -1]))).toEqual([
        ["Uno", 50],
        ["Dos", 50],
      ]);
    });

    test("Scenario 3: an Important Statement weighs double", async () => {
      await openSix();
      walk([AGREE, AGREE, AGREE, AGREE, AGREE, { label: "En desacuerdo", important: true }]);
      expect(rowTexts()).toEqual([
        `Partido Uno P1 71${NBSP}%5 de 6 coincidencias`,
        `Partido Dos P2 33${NBSP}%1 de 5 coincidencias`,
      ]);
      expect(screen.getByText("Has marcado 1 afirmación como importante.")).toBeTruthy();
      expect(enginePercent(engineAnswers([1, 1, 1, 1, 1, -1], [106]))).toEqual([
        ["Uno", 71],
        ["Dos", 33],
      ]);
    });

    test("Scenario 4: everything Neutral shows the prompt; answering one shows a ranking", async () => {
      await openSix();
      walk(["neutral", "neutral", "neutral", "neutral", "neutral", "neutral"]);
      expect(heading2().textContent).toBe("Tus resultados");
      expect(screen.getByText(PROMPT)).toBeTruthy();
      expect(screen.queryByRole("list", { name: "Tus resultados" })).toBeNull();
      // Only the summary donut shows a percentage.
      expect(screen.getAllByText(/%/).map((element) => element.className)).toEqual([
        "summary-donut__label",
      ]);
      expect(screen.queryByText(LEGEND)).toBeNull();
      expect(
        screen.getByRole("link", { name: "Cómo se calcula la afinidad (se abre en una pestaña nueva)" }),
      ).toBeTruthy();
      expect(screen.queryByText(LOSS_NOTE)).toBeNull();

      // Scenario 8 (quick answer): the prompt sends the Voter to Repetir cuestionario.
      expect(screen.queryByRole("region", { name: "Comparte tu resultado" })).toBeNull();
      restartQuestionnaire();
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(document.activeElement).toBe(heading2());
      walk([AGREE, "neutral", "neutral", "neutral", "neutral", "neutral"]);
      expect(screen.queryByText(PROMPT)).toBeNull();
      // Statement 1: Uno +1, same side; Dos has no stance there, so no score.
      expect(rowTexts()).toEqual([
        `Partido Uno P1 100${NBSP}%1 de 1 coincidencia Baja cobertura${LEGEND}`,
        `Partido Dos P2 Sin afirmaciones comparables0 de 0 coincidencias Baja cobertura${LEGEND}`,
      ]);
    });

    test("Repetir cuestionario starts over; the same Answers give the same ranking", async () => {
      await openSix();
      const steps: Step[] = [
        { label: "De acuerdo", important: true },
        AGREE,
        AGREE,
        AGREE,
        AGREE,
        { label: "En desacuerdo", important: true },
      ];
      walk(steps);
      const before = rowTexts();
      expect(screen.getByText("Has marcado 2 afirmaciones como importantes.")).toBeTruthy();

      restartQuestionnaire();
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(document.activeElement).toBe(heading2());
      expect(button("Importante para mí").getAttribute("aria-pressed")).toBe("false");
      walk(steps);
      expect(heading2().textContent).toBe("Tus resultados");
      expect(rowTexts()).toEqual(before);
    });

    test("Scenario 6: the methodology link opens METHODOLOGY_PATH in a new tab, on results and prompt", async () => {
      await openSix();
      walk([AGREE, "neutral", "neutral", "neutral", "neutral", "neutral"]);
      const name = "Cómo se calcula la afinidad (se abre en una pestaña nueva)";
      for (const pass of ["ranking", "prompt"]) {
        if (pass === "prompt") {
          restartQuestionnaire();
          walk(["neutral", "neutral", "neutral", "neutral", "neutral", "neutral"]);
          expect(screen.getByText(PROMPT)).toBeTruthy();
        } else {
          expect(screen.getByRole("list", { name: "Tus resultados" })).toBeTruthy();
        }
        const link = screen.getByRole("link", { name });
        expect(link.getAttribute("href")).toBe(METHODOLOGY_PATH);
        expect(link.getAttribute("target")).toBe("_blank");
        expect(link.getAttribute("rel")).toContain("noopener");
        expect(link.className).toBe("text-link");
      }
    });

    test("Scenario 7: Answers never leave the component; a reload starts over", async () => {
      const fetch = happyFetch(6);
      const view = await openSix(fetch);
      walk([AGREE, { label: "De acuerdo", important: true }, "neutral", AGREE, AGREE, AGREE]);
      expect(screen.getByRole("list", { name: "Tus resultados" })).toBeTruthy();
      expect(currentUrl).toBe("/elecciones/1/cuestionario");
      expect(apiPaths(fetch)).toEqual([ELECTION_URL, VERSION_URL]);
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
      expect(document.cookie).toBe("");

      view.unmount();
      await openSix(fetch);
      expect(heading2().textContent).toBe("Afirmación de prueba 1");
      expect(screen.queryByRole("button", { name: "Anterior" })).toBeNull();
      expect(button("Importante para mí").getAttribute("aria-pressed")).toBe("false");
    });

    test("feedback-dialog Scenario 7: sending feedback keeps the Answers, the URL and history", async () => {
      const fetch = routes({
        [ELECTION_URL]: () => jsonResponse(electionJson()),
        [VERSION_URL]: () => jsonResponse(datasetVersionJson({ statements: 6 })),
        "/api/v1/feedback": () => jsonResponse({ status: "ok" }, 201),
      });
      await openSix(fetch);
      walk([AGREE, AGREE, AGREE, AGREE, AGREE, { label: "De acuerdo", important: true }]);
      const before = {
        ranking: rowTexts(),
        summary: screen.getByText(/Muestra evaluada:/).textContent,
        url: currentUrl,
        history: window.history.length,
      };

      // Placement: right after the share card.
      const feedback = button("Danos tu opinión");
      expect(feedback.className).toBe("button-secondary");
      expect(document.querySelector(".results-dashboard .share-card")?.nextElementSibling).toBe(
        feedback.parentElement,
      );

      fireEvent.click(feedback);
      const dialog = screen.getByRole("dialog", { name: "Ayúdanos a mejorar" });
      fireEvent.change(within(dialog).getByRole("textbox", { name: "Tu opinión" }), {
        target: { value: "Interesante" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Enviar" }));
      await within(dialog).findByText("¡Gracias por tu opinión!");
      fireEvent.click(within(dialog).getAllByRole("button", { name: "Cerrar" })[1]!);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.activeElement).toBe(button("Danos tu opinión"));

      const posts = fetch.mock.calls.filter(([url]) => url === "/api/v1/feedback");
      expect(posts).toHaveLength(1);
      expect(posts[0]![1]?.method).toBe("POST");
      const body = JSON.parse(String(posts[0]![1]?.body)) as Record<string, unknown>;
      expect(body).toEqual({ message: "Interesante", origin: "results" });
      expect(apiPaths(fetch)).toEqual([
        ELECTION_URL,
        VERSION_URL,
        "/api/v1/feedback",
      ]);

      expect({
        ranking: rowTexts(),
        summary: screen.getByText(/Muestra evaluada:/).textContent,
        url: currentUrl,
        history: window.history.length,
      }).toEqual(before);
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);

      // Cancelling Repetir keeps the result as it was.
      fireEvent.click(button("Repetir cuestionario"));
      fireEvent.click(button("Cancelar"));
      expect(rowTexts()).toEqual(before.ranking);
    });
  });
});
