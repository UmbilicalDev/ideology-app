// View helpers for the results breakdown (DESIGN.md "Statement matrix" and
// "Breakdown filters"): the answer filters, the stance labels and the
// per-cell coincidence. Pure: no React, DOM or request.
import {
  NO_STANCE,
  SKIP,
  statementAgreement,
  type BreakdownPosition,
  type BreakdownRow,
} from "@ideology-app/core";

import { SCALE_LABELS } from "../scale-labels";

export type BreakdownFilter = "all" | "agree" | "neutral" | "disagree" | "skipped" | "important";

export const BREAKDOWN_FILTERS: readonly { readonly id: BreakdownFilter; readonly label: string }[] = [
  { id: "all", label: "Todas" },
  { id: "agree", label: "De acuerdo" },
  { id: "neutral", label: "Neutral" },
  { id: "disagree", label: "En desacuerdo" },
  { id: "skipped", label: "Saltadas" },
  { id: "important", label: "Importantes" },
];

/** Whether a row passes a filter. "De acuerdo" and "En desacuerdo" include their "Muy" grade. */
export function matchesFilter(row: BreakdownRow, filter: BreakdownFilter): boolean {
  const { answer } = row;
  switch (filter) {
    case "all":
      return true;
    case "agree":
      return answer === 1 || answer === 2;
    case "neutral":
      return answer === 0;
    case "disagree":
      return answer === -1 || answer === -2;
    case "skipped":
      return answer === SKIP;
    case "important":
      return row.important;
  }
}

export function stanceLabel(position: BreakdownPosition, noStanceLabel: string): string {
  return position.value === NO_STANCE ? noStanceLabel : SCALE_LABELS[position.value];
}

/**
 * The coincidence of a rated Answer with a Party's Position, in percent (100,
 * 75, 50, 25 or 0, the matching rule's per-Statement agreement), or `null`
 * when the row has no rated Answer or the Party has no stance.
 */
export function coincidence(row: BreakdownRow, position: BreakdownPosition): number | null {
  if (row.answer === null || row.answer === SKIP || position.value === NO_STANCE) {
    return null;
  }
  return Math.round(statementAgreement(row.answer, position.value) * 100);
}
