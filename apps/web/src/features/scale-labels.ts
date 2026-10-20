import type { ScaleValue } from "@ideology-app/core";

/**
 * The five scale labels, defined once for the Questionnaire options and the
 * results breakdown. Meaning is carried by the text, never by colour alone
 * (DESIGN.md).
 */
export const SCALE_LABELS: Readonly<Record<ScaleValue, string>> = {
  [-2]: "Muy en desacuerdo",
  [-1]: "En desacuerdo",
  0: "Ni de acuerdo ni en desacuerdo",
  1: "De acuerdo",
  2: "Muy de acuerdo",
};
