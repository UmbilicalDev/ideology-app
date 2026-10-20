// Share Link codec: the payload after "#" in a Share Link. Pure: no React,
// DOM, `URL`, storage or network; string operations and regexes only.
//
// Format v1: `v1-<datasetVersionId>-<answers>`, e.g. `v1-7-ddddddASssss`.
// - `<datasetVersionId>`: 1..2147483647, no leading zero (the API id bound).
// - `<answers>`: one letter per Statement in the Dataset Version's Statement
//   order: -2..2 → a..e, skip → s; upper case means marked Important (a
//   flagged skip keeps its flag). 1..500 letters.
// Keyed by position, not by Statement id: Dataset Versions are immutable, so
// the version id fixes the order. A truncated link has too few letters and
// fails `restoreQuestionnaire` with `statement_count_mismatch`.
//
// Versioning: any layout change gets a new marker (`v2`...). Decoders keep
// accepting every earlier version, because old links pin old Dataset
// Versions (CONSTRAINTS.md, Client-side Matching).
import { SKIP } from "../../domain/match-score";
import type { AnswerValue, QuestionnaireState } from "../../domain/questionnaire";

export const SHARE_LINK_FORMAT_VERSION = 1;
export const MAX_SHARE_LINK_STATEMENTS = 500;

const MAX_DATASET_VERSION_ID = 2147483647;
const MAX_FRAGMENT_LENGTH = 1024;
const VERSION_MARKER_PATTERN = /^v([1-9][0-9]{0,2})-/;
const V1_PATTERN = /^v1-([1-9][0-9]{0,9})-([a-esA-ES]{1,500})$/;

export interface ShareLinkEntry {
  readonly value: AnswerValue;
  readonly important: boolean;
}

export interface ShareLink {
  readonly formatVersion: 1;
  readonly datasetVersionId: number;
  readonly entries: readonly ShareLinkEntry[];
}

export type ShareLinkErrorKind = "malformed" | "unsupported_version" | "statement_count_mismatch";

export class ShareLinkError extends Error {
  readonly kind: ShareLinkErrorKind;

  constructor(kind: ShareLinkErrorKind, message: string) {
    super(`share link: ${message}`);
    this.name = "ShareLinkError";
    this.kind = kind;
  }
}

// Fixed lookup tables: decoded values are valid by construction.
const LETTER_BY_VALUE: ReadonlyMap<AnswerValue, string> = new Map<AnswerValue, string>([
  [-2, "a"],
  [-1, "b"],
  [0, "c"],
  [1, "d"],
  [2, "e"],
  [SKIP, "s"],
]);

const VALUE_BY_LETTER: ReadonlyMap<string, AnswerValue> = new Map(
  [...LETTER_BY_VALUE].map(([value, letter]) => [letter, value]),
);

function isValidDatasetVersionId(id: number): boolean {
  return Number.isInteger(id) && id >= 1 && id <= MAX_DATASET_VERSION_ID;
}

/**
 * The payload (without "#") for a finished Questionnaire. Throws `RangeError`
 * for an invalid id, no or more than 500 Statements, or a Statement without
 * an Answer.
 */
export function encodeShareLink(state: QuestionnaireState, datasetVersionId: number): string {
  if (!isValidDatasetVersionId(datasetVersionId)) {
    throw new RangeError(`share link: invalid Dataset Version id ${String(datasetVersionId)}`);
  }
  const count = state.statementIds.length;
  if (count === 0 || count > MAX_SHARE_LINK_STATEMENTS) {
    throw new RangeError(
      `share link: expected 1 to ${MAX_SHARE_LINK_STATEMENTS} Statements, got ${count}`,
    );
  }
  let letters = "";
  for (const statementId of state.statementIds) {
    const value = state.answers.get(statementId);
    const letter = value === undefined ? undefined : LETTER_BY_VALUE.get(value);
    if (letter === undefined) {
      throw new RangeError(`share link: Statement ${statementId} has no Answer`);
    }
    letters += state.important.has(statementId) ? letter.toUpperCase() : letter;
  }
  return `v${SHARE_LINK_FORMAT_VERSION}-${datasetVersionId}-${letters}`;
}

/**
 * Parses the text after "#" (untrusted input). Strict: anything but an exact
 * v1 payload throws `ShareLinkError`; it never returns partial data.
 */
export function decodeShareLink(fragment: string): ShareLink {
  if (fragment.length > MAX_FRAGMENT_LENGTH) {
    throw new ShareLinkError("malformed", "the link is too long");
  }
  const marker = VERSION_MARKER_PATTERN.exec(fragment);
  if (marker !== null && marker[1] !== String(SHARE_LINK_FORMAT_VERSION)) {
    throw new ShareLinkError("unsupported_version", `unsupported format version v${marker[1]}`);
  }
  const match = V1_PATTERN.exec(fragment);
  if (match === null) {
    throw new ShareLinkError("malformed", "answers contain an invalid character or the layout is wrong");
  }
  const datasetVersionId = Number(match[1]);
  if (datasetVersionId > MAX_DATASET_VERSION_ID) {
    throw new ShareLinkError("malformed", "the Dataset Version id is out of range");
  }
  const entries: ShareLinkEntry[] = [];
  for (const char of match[2]!) {
    const lower = char.toLowerCase();
    const value = VALUE_BY_LETTER.get(lower);
    if (value === undefined) {
      throw new ShareLinkError("malformed", "answers contain an invalid character");
    }
    entries.push({ value, important: char !== lower });
  }
  return { formatVersion: 1, datasetVersionId, entries };
}

/**
 * The end-screen Questionnaire state for a decoded link and the Dataset
 * Version's Statement ids in position order. Throws `ShareLinkError`
 * (`statement_count_mismatch`) when the counts differ.
 */
export function restoreQuestionnaire(
  link: ShareLink,
  statementIds: readonly number[],
): QuestionnaireState {
  if (link.entries.length !== statementIds.length) {
    throw new ShareLinkError(
      "statement_count_mismatch",
      `the link has ${link.entries.length} answers but the Dataset Version has ${statementIds.length} Statements`,
    );
  }
  const answers = new Map<number, AnswerValue>();
  const important = new Set<number>();
  statementIds.forEach((statementId, i) => {
    const entry = link.entries[i]!;
    answers.set(statementId, entry.value);
    if (entry.important) {
      important.add(statementId);
    }
  });
  return {
    statementIds: [...statementIds],
    currentIndex: statementIds.length,
    answers,
    important,
  };
}
