// Match Score engine. Implements the Matching Rule in docs/build-brief.md.
//
// Runs in the Voter's browser so Answers never reach the server. Pure,
// dependency-free module: no imports, no browser or network globals.
//
// For each Statement with an Answer other than SKIP and a Party Position other
// than NO_STANCE: agreement = 1 - |answer - position| / 4, weight = 2 when the
// Answer is Important, else 1. Match Score = sum(weight * agreement) / sum(weight),
// or null when no Statement is shared. Fewer than N shared Statements is
// flagged as low coverage.
//
// The input comes from untrusted sources (a Share Link fragment), so the
// runtime checks stay even though the types describe valid input.

export const SKIP = "skip" as const;
export const NO_STANCE = "no_stance" as const;
export const IMPORTANT_WEIGHT = 2 as const;
export const LOW_COVERAGE_THRESHOLD = 5 as const;

export type ScaleValue = -2 | -1 | 0 | 1 | 2;
export type StatementId = number | string;

export interface Answer {
  statementId: StatementId;
  value: ScaleValue | typeof SKIP;
  important?: boolean | undefined;
}

export interface PositionInput {
  statementId: StatementId;
  value: ScaleValue | typeof NO_STANCE;
}

export interface PartyInput<P> {
  partyId: P;
  positions: readonly PositionInput[];
}

export interface MatchScoreOptions {
  lowCoverageThreshold?: number | undefined;
}

export interface MatchScoreResult {
  matchScore: number | null;
  sharedStatementCount: number;
  lowCoverage: boolean;
}

interface Entry {
  statementId: unknown;
  value: unknown;
  important?: unknown;
}

function isScaleValue(value: unknown): value is ScaleValue {
  return Number.isInteger(value) && (value as number) >= -2 && (value as number) <= 2;
}

function describe(value: unknown): string {
  return typeof value === "string" ? JSON.stringify(value) : String(value);
}

function checkArray(value: unknown, field: string): asserts value is readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new TypeError(`${field} must be an array`);
  }
}

function checkThreshold(options: unknown): number {
  if (options === null || typeof options !== "object") {
    throw new TypeError("options must be an object");
  }
  const threshold: unknown =
    (options as { lowCoverageThreshold?: unknown }).lowCoverageThreshold ?? LOW_COVERAGE_THRESHOLD;
  if (!Number.isInteger(threshold) || (threshold as number) < 1) {
    throw new RangeError(
      `options.lowCoverageThreshold must be a positive integer, got ${describe(threshold)}`,
    );
  }
  return threshold as number;
}

// Validates entries and indexes them by String(statementId).
function indexEntries(
  entries: unknown,
  field: string,
  isValidValue: (value: unknown) => boolean,
  allowed: string,
): Map<string, Entry> {
  checkArray(entries, field);
  const byId = new Map<string, Entry>();
  entries.forEach((entry, i) => {
    if (entry === null || typeof entry !== "object") {
      throw new TypeError(`${field}[${i}] must be an object`);
    }
    const { statementId, value } = entry as Entry;
    if (typeof statementId !== "number" && typeof statementId !== "string") {
      throw new TypeError(`${field}[${i}].statementId must be a number or a string`);
    }
    const id = String(statementId);
    if (!isValidValue(value)) {
      throw new RangeError(
        `${field}[${i}].value for statementId ${id} must be ${allowed}, got ${describe(value)}`,
      );
    }
    if (byId.has(id)) {
      throw new RangeError(`${field} has a duplicate statementId ${id}`);
    }
    byId.set(id, entry as Entry);
  });
  return byId;
}

function indexAnswers(answers: unknown): Map<string, Entry> {
  const byId = indexEntries(
    answers,
    "answers",
    (v) => v === SKIP || isScaleValue(v),
    `an integer from -2 to 2 or "${SKIP}"`,
  );
  for (const [id, answer] of byId) {
    if (answer.important !== undefined && typeof answer.important !== "boolean") {
      throw new TypeError(
        `answers.important for statementId ${id} must be a boolean, got ${describe(answer.important)}`,
      );
    }
  }
  return byId;
}

function indexPositions(positions: unknown, field = "positions"): Map<string, Entry> {
  return indexEntries(
    positions,
    field,
    (v) => v === NO_STANCE || isScaleValue(v),
    `an integer from -2 to 2 or "${NO_STANCE}"`,
  );
}

export function statementAgreement(answerValue: ScaleValue, positionValue: ScaleValue): number {
  if (!isScaleValue(answerValue)) {
    throw new RangeError(`answerValue must be an integer from -2 to 2, got ${describe(answerValue)}`);
  }
  if (!isScaleValue(positionValue)) {
    throw new RangeError(
      `positionValue must be an integer from -2 to 2, got ${describe(positionValue)}`,
    );
  }
  return 1 - Math.abs(answerValue - positionValue) / 4;
}

function score(
  answersById: Map<string, Entry>,
  positionsById: Map<string, Entry>,
  threshold: number,
): MatchScoreResult {
  let weighted = 0;
  let totalWeight = 0;
  let shared = 0;
  for (const [id, answer] of answersById) {
    if (answer.value === SKIP) continue;
    const position = positionsById.get(id);
    if (position === undefined || position.value === NO_STANCE) continue;
    const weight = answer.important === true ? IMPORTANT_WEIGHT : 1;
    weighted += weight * statementAgreement(answer.value as ScaleValue, position.value as ScaleValue);
    totalWeight += weight;
    shared += 1;
  }
  return {
    matchScore: totalWeight === 0 ? null : weighted / totalWeight,
    sharedStatementCount: shared,
    lowCoverage: shared < threshold,
  };
}

export function computeMatchScore(
  answers: readonly Answer[],
  positions: readonly PositionInput[],
  options: MatchScoreOptions = {},
): MatchScoreResult {
  const threshold = checkThreshold(options);
  return score(indexAnswers(answers), indexPositions(positions), threshold);
}

export function computeMatchScores<P>(
  answers: readonly Answer[],
  parties: readonly PartyInput<P>[],
  options: MatchScoreOptions = {},
): (MatchScoreResult & { partyId: P })[] {
  const threshold = checkThreshold(options);
  const answersById = indexAnswers(answers);
  checkArray(parties, "parties");
  return parties.map((party, i) => {
    if (party === null || typeof party !== "object") {
      throw new TypeError(`parties[${i}] must be an object`);
    }
    const positionsById = indexPositions(party.positions, `parties[${i}].positions`);
    return { partyId: party.partyId, ...score(answersById, positionsById, threshold) };
  });
}
