import { NEUTRAL, positionSide, type AnswerValue, type ScaleValue } from "@ideology-app/core";

/**
 * The three Answer labels, defined once for the Questionnaire options and the
 * results breakdown. Meaning is carried by the text, never by colour alone
 * (DESIGN.md).
 */
export const ANSWER_LABELS: Readonly<Record<"-1" | "1" | typeof NEUTRAL, string>> = {
  [-1]: "En desacuerdo",
  [NEUTRAL]: "Neutral / No lo sé",
  1: "De acuerdo",
};

export function answerLabel(value: AnswerValue): string {
  return ANSWER_LABELS[value === NEUTRAL ? NEUTRAL : value === 1 ? "1" : "-1"];
}

/**
 * A stored Party Position read by side, the way the Match Score reads it:
 * +1/+2 De acuerdo, -1/-2 En desacuerdo, 0 Neutral. Intensity is not shown,
 * because it does not count; the Evidence quote keeps the nuance.
 */
export function stanceSideLabel(value: ScaleValue): string {
  const side = positionSide(value);
  if (side === null) return "Neutral";
  return side === 1 ? "De acuerdo" : "En desacuerdo";
}
