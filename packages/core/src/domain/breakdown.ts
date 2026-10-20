// Results breakdown: one row per Statement with the Voter's Answer and every
// Party's Position and Evidence. Pure: no React, DOM, storage or network.
// Built in memory from the loaded Dataset Version and the Answers; nothing
// here is sent anywhere.
//
// Party order inside every row is `partyOrder` (the `rankParties` order on
// the results screen), so a Party sits in the same place in every row and in
// the ranking (CONSTRAINTS.md, Client-side Matching).
import type { Party, Statement } from "./dataset-version";
import { NO_STANCE, SKIP, type Answer, type ScaleValue } from "./match-score";

export interface EvidenceView {
  readonly quote: string;
  readonly page: number;
  /** `url#page=N` for URL Source Documents, `null` for uploads or unsafe URLs. */
  readonly href: string | null;
}

export interface BreakdownPosition {
  readonly partyId: number;
  readonly name: string;
  readonly shortName: string;
  readonly value: ScaleValue | typeof NO_STANCE;
  /** `null` exactly when `value` is `no_stance`. */
  readonly evidence: EvidenceView | null;
}

export interface BreakdownRow {
  readonly statementId: number;
  readonly position: number;
  readonly text: string;
  /** The Voter's Answer, or `null` when the Statement has none. */
  readonly answer: ScaleValue | typeof SKIP | null;
  /** `true` only for a rated (not skipped) Answer flagged Important. */
  readonly important: boolean;
  readonly positions: readonly BreakdownPosition[];
}

// Absolute http(s) URL with no whitespace. Core has no `URL` global
// (`lib: ES2022`, `types: []`), so this is string logic; it rejects
// `javascript:`, relative and other-scheme URLs.
const HTTP_URL = /^https?:\/\/\S+$/i;

/** The Evidence locator link: the Source Document URL plus `#page=N`. */
export function evidenceHref(evidence: { readonly url: string | null; readonly page: number }): string | null {
  if (evidence.url === null) {
    return null;
  }
  const url = evidence.url.trim();
  if (!HTTP_URL.test(url)) {
    return null;
  }
  const hash = url.indexOf("#");
  const base = hash === -1 ? url : url.slice(0, hash);
  return `${base}#page=${evidence.page}`;
}

function orderParties(parties: readonly Party[], partyOrder: readonly number[]): Party[] {
  const rank = new Map<number, number>();
  partyOrder.forEach((id, i) => {
    if (!rank.has(id)) rank.set(id, i);
  });
  const known = parties.filter((p) => rank.has(p.id));
  const rest = parties.filter((p) => !rank.has(p.id));
  known.sort((a, b) => rank.get(a.id)! - rank.get(b.id)!);
  return [...known, ...rest];
}

function toPosition(party: Party, statementId: number): BreakdownPosition {
  const found = party.positions.find((p) => p.statementId === statementId);
  const base = { partyId: party.id, name: party.name, shortName: party.shortName };
  if (found === undefined || found.value === NO_STANCE || found.evidence === null) {
    return { ...base, value: NO_STANCE, evidence: null };
  }
  const { quote, page } = found.evidence;
  return {
    ...base,
    value: found.value,
    evidence: { quote, page, href: evidenceHref(found.evidence) },
  };
}

/**
 * One row per Statement (in `statements` order) with the Voter's Answer and
 * every Party's Position in `partyOrder` order. Party ids missing from
 * `partyOrder` come after, in input order; unknown ids in `partyOrder` are
 * ignored. A missing Position is shown as `no_stance`. Inputs are not changed.
 */
export function buildBreakdown(
  statements: readonly Statement[],
  parties: readonly Party[],
  answers: readonly Answer[],
  partyOrder: readonly number[],
): BreakdownRow[] {
  const answersById = new Map<string, Answer>();
  for (const answer of answers) {
    answersById.set(String(answer.statementId), answer);
  }
  const ordered = orderParties(parties, partyOrder);
  return statements.map((statement): BreakdownRow => {
    const answer = answersById.get(String(statement.id));
    const value = answer === undefined ? null : answer.value;
    return {
      statementId: statement.id,
      position: statement.position,
      text: statement.text,
      answer: value,
      important: value !== null && value !== SKIP && answer?.important === true,
      positions: ordered.map((party) => toPosition(party, statement.id)),
    };
  });
}
