// Share Link codec: the payload after "#" in a Share Link. Pure: no React,
// DOM, `URL`, storage or network; string operations and regexes only.
//
// Format v2: `v2-<datasetVersionId>-<answers>`, e.g. `v2-7-ddnnaAAN`.
// - `<datasetVersionId>`: 1..2147483647, no leading zero (the API id bound).
// - `<answers>`: one letter per Statement in the Dataset Version's Statement
//   order: d = -1 (En desacuerdo), n = Neutral / No lo sé, a = 1 (De acuerdo);
//   upper case means marked Important (a flagged Neutral Answer keeps its
//   flag). 1..500 letters.
// Keyed by position, not by Statement id: Dataset Versions are immutable, so
// the version id fixes the order. A truncated link has too few letters and
// fails `restoreQuestionnaire` with `statement_count_mismatch`.
//
// Versioning: any layout change gets a new marker (`v3`...). Decoders keep
// accepting every earlier marker unless a user decision retires it; a retired
// marker is recognised and reported as `outdated_version`, never a generic
// error (CONSTRAINTS.md, Client-side Matching). `v1` (five-point scale plus
// skip) was retired on 2026-11-21 by `three-option-scale`: its result cannot
// be shown the same way under the three-option rule, so it is not decoded.
import { NEUTRAL } from "../../domain/match-score";
import type { AnswerValue, QuestionnaireState } from "../../domain/questionnaire";

export const SHARE_LINK_FORMAT_VERSION = 2;
export const MAX_SHARE_LINK_STATEMENTS = 500;

const MAX_DATASET_VERSION_ID = 2147483647;
const MAX_FRAGMENT_LENGTH = 1024;
const VERSION_MARKER_PATTERN = /^v([1-9][0-9]{0,2})-/;
const V2_PATTERN = /^v2-([1-9][0-9]{0,9})-([dnaDNA]{1,500})$/;
const RETIRED_MARKERS: ReadonlySet<string> = new Set(["1"]);
const V1_ID_PATTERN = /^v1-([1-9][0-9]{0,9})-/;

export interface ShareLinkEntry {
  readonly value: AnswerValue;
  readonly important: boolean;
}

export interface ShareLink {
  readonly formatVersion: 2;
  readonly datasetVersionId: number;
  readonly entries: readonly ShareLinkEntry[];
}

export type ShareLinkErrorKind =
  | "malformed"
  | "unsupported_version"
  | "outdated_version"
  | "statement_count_mismatch";

export class ShareLinkError extends Error {
  readonly kind: ShareLinkErrorKind;
  /** For `outdated_version`: the Dataset Version id when the old link names a valid one. */
  readonly datasetVersionId: number | undefined;

  constructor(kind: ShareLinkErrorKind, message: string, datasetVersionId?: number) {
    super(`share link: ${message}`);
    this.name = "ShareLinkError";
    this.kind = kind;
    this.datasetVersionId = datasetVersionId;
  }
}

// Fixed lookup tables: decoded values are valid by construction.
const LETTER_BY_VALUE: ReadonlyMap<AnswerValue, string> = new Map<AnswerValue, string>([
  [-1, "d"],
  [NEUTRAL, "n"],
  [1, "a"],
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
 * v2 payload throws `ShareLinkError`; it never returns partial data. Any
 * fragment with the retired `v1` marker throws `outdated_version`, carrying
 * the Dataset Version id when one parses within range.
 */
export function decodeShareLink(fragment: string): ShareLink {
  if (fragment.length > MAX_FRAGMENT_LENGTH) {
    throw new ShareLinkError("malformed", "the link is too long");
  }
  const marker = VERSION_MARKER_PATTERN.exec(fragment);
  if (marker !== null && RETIRED_MARKERS.has(marker[1]!)) {
    throw new ShareLinkError(
      "outdated_version",
      `format version v${marker[1]} belongs to an earlier version of the questionnaire`,
      outdatedDatasetVersionId(fragment),
    );
  }
  if (marker !== null && marker[1] !== String(SHARE_LINK_FORMAT_VERSION)) {
    throw new ShareLinkError("unsupported_version", `unsupported format version v${marker[1]}`);
  }
  const match = V2_PATTERN.exec(fragment);
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
  return { formatVersion: 2, datasetVersionId, entries };
}

function outdatedDatasetVersionId(fragment: string): number | undefined {
  const match = V1_ID_PATTERN.exec(fragment);
  if (match === null) {
    return undefined;
  }
  const id = Number(match[1]);
  return isValidDatasetVersionId(id) ? id : undefined;
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
