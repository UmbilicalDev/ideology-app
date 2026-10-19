// Match Score engine. Implements the Matching Rule in docs/build-brief.md.
//
// Runs in the Voter's browser so Answers never reach the server. Pure,
// dependency-free ES module: no imports, no browser or network globals.
//
// For each Statement with an Answer other than SKIP and a Party Position other
// than NO_STANCE: agreement = 1 - |answer - position| / 4, weight = 2 when the
// Answer is Important, else 1. Match Score = sum(weight * agreement) / sum(weight),
// or null when no Statement is shared. Fewer than N shared Statements is
// flagged as low coverage.

export const SKIP = "skip";
export const NO_STANCE = "no_stance";
export const IMPORTANT_WEIGHT = 2;
export const LOW_COVERAGE_THRESHOLD = 5;

function isScaleValue(value) {
  return Number.isInteger(value) && value >= -2 && value <= 2;
}

function describe(value) {
  return typeof value === "string" ? JSON.stringify(value) : String(value);
}

function checkArray(value, field) {
  if (!Array.isArray(value)) {
    throw new TypeError(`${field} must be an array`);
  }
}

function checkThreshold(options) {
  if (options === null || typeof options !== "object") {
    throw new TypeError("options must be an object");
  }
  const threshold = options.lowCoverageThreshold ?? LOW_COVERAGE_THRESHOLD;
  if (!Number.isInteger(threshold) || threshold < 1) {
    throw new RangeError(
      `options.lowCoverageThreshold must be a positive integer, got ${describe(threshold)}`,
    );
  }
  return threshold;
}

// Validates entries and indexes them by String(statementId).
function indexEntries(entries, field, isValidValue, allowed) {
  checkArray(entries, field);
  const byId = new Map();
  entries.forEach((entry, i) => {
    if (entry === null || typeof entry !== "object") {
      throw new TypeError(`${field}[${i}] must be an object`);
    }
    const { statementId, value } = entry;
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
    byId.set(id, entry);
  });
  return byId;
}

function indexAnswers(answers) {
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

function indexPositions(positions, field = "positions") {
  return indexEntries(
    positions,
    field,
    (v) => v === NO_STANCE || isScaleValue(v),
    `an integer from -2 to 2 or "${NO_STANCE}"`,
  );
}

export function statementAgreement(answerValue, positionValue) {
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

function score(answersById, positionsById, threshold) {
  let weighted = 0;
  let totalWeight = 0;
  let shared = 0;
  for (const [id, answer] of answersById) {
    if (answer.value === SKIP) continue;
    const position = positionsById.get(id);
    if (position === undefined || position.value === NO_STANCE) continue;
    const weight = answer.important === true ? IMPORTANT_WEIGHT : 1;
    weighted += weight * statementAgreement(answer.value, position.value);
    totalWeight += weight;
    shared += 1;
  }
  return {
    matchScore: totalWeight === 0 ? null : weighted / totalWeight,
    sharedStatementCount: shared,
    lowCoverage: shared < threshold,
  };
}

export function computeMatchScore(answers, positions, options = {}) {
  const threshold = checkThreshold(options);
  return score(indexAnswers(answers), indexPositions(positions), threshold);
}

export function computeMatchScores(answers, parties, options = {}) {
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
