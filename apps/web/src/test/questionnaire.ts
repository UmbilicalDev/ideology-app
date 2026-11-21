// Walking the Questionnaire in tests: one tap per Statement (answer buttons
// that advance, spec questionnaire-quick-answer).
import { fireEvent, screen, within } from "@testing-library/react";

import { NEUTRAL, type AnswerValue } from "@ideology-app/core";

export type AnswerName = "En desacuerdo" | "Neutral / No lo sé" | "De acuerdo";

/** The answer buttons, in their order: En desacuerdo, Neutral / No lo sé, De acuerdo. */
export const ANSWER_NAMES: readonly AnswerName[] = ["En desacuerdo", "Neutral / No lo sé", "De acuerdo"];

export function answerName(value: AnswerValue): AnswerName {
  return value === NEUTRAL ? "Neutral / No lo sé" : value === 1 ? "De acuerdo" : "En desacuerdo";
}

/** The answer button of the Statement shown now. */
export function answerButton(name: AnswerName): HTMLButtonElement {
  const group = document.querySelector<HTMLElement>(".answer-controls");
  if (group === null) {
    throw new Error("no answer buttons on screen");
  }
  return within(group).getByRole("button", { name }) as HTMLButtonElement;
}

export type WalkStep = AnswerValue | { readonly value: AnswerValue; readonly important: true };

/**
 * Answers the next Statements in order, one tap each; `{ value, important }`
 * presses Importante para mí first.
 */
export function answerAll(steps: readonly WalkStep[]): void {
  for (const step of steps) {
    const value = typeof step === "object" ? step.value : step;
    if (typeof step === "object") {
      fireEvent.click(screen.getByRole("button", { name: "Importante para mí" }));
    }
    fireEvent.click(answerButton(answerName(value)));
  }
}

/** Waits for the first Statement's answer buttons. */
export function findAnswerButtons(): Promise<HTMLElement> {
  return screen.findByRole("button", { name: "De acuerdo" });
}

/** `Repetir cuestionario`, then `Sí, repetir` in its confirmation dialog. */
export function restartQuestionnaire(): void {
  fireEvent.click(screen.getByRole("button", { name: "Repetir cuestionario" }));
  const dialog = screen.getByRole("dialog", { name: "¿Repetir el cuestionario?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Sí, repetir" }));
}
