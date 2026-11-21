// View helpers for the results breakdown (DESIGN.md "Statement matrix" and
// "Breakdown filters"): the answer filters, the stance labels and the
// per-cell coincidence. Pure: no React, DOM or request.
import {
  NEUTRAL,
  NO_STANCE,
  statementAgreement,
  type BreakdownPosition,
  type BreakdownRow,
} from "@ideology-app/core";

import { stanceSideLabel } from "../scale-labels";

export type BreakdownFilter = "all" | "agree" | "neutral" | "disagree" | "important";

export const BREAKDOWN_FILTERS: readonly { readonly id: BreakdownFilter; readonly label: string }[] = [
  { id: "all", label: "Todas" },
  { id: "agree", label: "De acuerdo" },
  { id: "neutral", label: "Neutral" },
  { id: "disagree", label: "En desacuerdo" },
  { id: "important", label: "Importantes" },
];

/** Whether a row passes a filter on the Voter's Answer or Important flag. */
export function matchesFilter(row: BreakdownRow, filter: BreakdownFilter): boolean {
  const { answer } = row;
  switch (filter) {
    case "all":
      return true;
    case "agree":
      return answer === 1;
    case "neutral":
      return answer === NEUTRAL;
    case "disagree":
      return answer === -1;
    case "important":
      return row.important;
  }
}

export function stanceLabel(position: BreakdownPosition, noStanceLabel: string): string {
  return position.value === NO_STANCE ? noStanceLabel : stanceSideLabel(position.value);
}

/**
 * The coincidence of a sided Answer with a Party's Position, in percent: 100
 * on the same side, 0 on opposite sides (the matching rule's per-Statement
 * agreement), or `null` when the row has no Answer, the Answer is Neutral, or
 * the Position is 0 or no stance (excluded from the Match Score).
 */
export function coincidence(row: BreakdownRow, position: BreakdownPosition): 100 | 0 | null {
  if (
    row.answer === null ||
    row.answer === NEUTRAL ||
    position.value === NO_STANCE ||
    position.value === 0
  ) {
    return null;
  }
  return statementAgreement(row.answer, position.value) === 1 ? 100 : 0;
}
