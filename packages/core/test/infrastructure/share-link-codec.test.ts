import { describe, expect, test } from "vitest";

import {
  MAX_SHARE_LINK_STATEMENTS,
  NO_STANCE,
  SHARE_LINK_FORMAT_VERSION,
  SKIP,
  ShareLinkError,
  decodeShareLink,
  encodeShareLink,
  rankParties,
  restoreQuestionnaire,
  toMatchScoreAnswers,
  type AnswerValue,
  type Party,
  type PartyPosition,
  type QuestionnaireState,
  type ShareLinkErrorKind,
} from "../../src/index";

const VALUES: readonly AnswerValue[] = [-2, -1, 0, 1, 2, SKIP];
const LETTERS = ["a", "b", "c", "d", "e", "s"];

function finished(
  entries: readonly (readonly [AnswerValue, boolean])[],
  ids: readonly number[] = entries.map((_, i) => 101 + i),
): QuestionnaireState {
  const answers = new Map<number, AnswerValue>();
  const important = new Set<number>();
  entries.forEach(([value, flagged], i) => {
    answers.set(ids[i]!, value);
    if (flagged) important.add(ids[i]!);
  });
  return { statementIds: [...ids], currentIndex: ids.length, answers, important };
}

function expectError(run: () => unknown, kind: ShareLinkErrorKind) {
  let caught: unknown;
  try {
    run();
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(ShareLinkError);
  expect((caught as ShareLinkError).kind).toBe(kind);
  expect((caught as ShareLinkError).message).toMatch(/^share link: /);
}

// Deterministic PRNG (mulberry32) so the random round-trip is reproducible.
function prng(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function partiesFor(ids: readonly number[], random: () => number): Party[] {
  const stances = [-2, -1, 0, 1, 2, NO_STANCE] as const;
  return [1, 2, 3].map((partyId) => {
    const positions: PartyPosition[] = ids.map((statementId) => {
      const value = stances[Math.floor(random() * stances.length)]!;
      return {
        statementId,
        value,
        evidence:
          value === NO_STANCE ? null : { quote: "Cita.", page: 1, url: null, sourceDocumentId: 1 },
      };
    });
    return { id: partyId, name: `Partido ${partyId}`, shortName: `P${partyId}`, positions };
  });
}

describe("encodeShareLink", () => {
  test("format version 1 and a 500-Statement cap", () => {
    expect(SHARE_LINK_FORMAT_VERSION).toBe(1);
    expect(MAX_SHARE_LINK_STATEMENTS).toBe(500);
  });

  test("all 12 symbols: each value with and without Important", () => {
    const entries = VALUES.flatMap((value) => [
      [value, false] as const,
      [value, true] as const,
    ]);
    expect(encodeShareLink(finished(entries), 7)).toBe("v1-7-aAbBcCdDeEsS");
    VALUES.forEach((value, i) => {
      expect(encodeShareLink(finished([[value, false]]), 1)).toBe(`v1-1-${LETTERS[i]}`);
      expect(encodeShareLink(finished([[value, true]]), 1)).toBe(`v1-1-${LETTERS[i]!.toUpperCase()}`);
    });
  });

  test("a flagged skip keeps its flag as S", () => {
    expect(encodeShareLink(finished([[1, false], [SKIP, true], [SKIP, false]]), 1)).toBe("v1-1-dSs");
  });

  test("the payload follows Statement order, not Statement id order", () => {
    const state = finished([[-2, false], [2, false]], [205, 3]);
    expect(encodeShareLink(state, 1)).toBe("v1-1-ae");
  });

  test("1 and 500 Statements; ids 1 and 2147483647", () => {
    expect(encodeShareLink(finished([[0, false]]), 1)).toBe("v1-1-c");
    const many = finished(Array.from({ length: 500 }, () => [SKIP, false] as const));
    const payload = encodeShareLink(many, 2147483647);
    expect(payload).toBe(`v1-2147483647-${"s".repeat(500)}`);
    expect(decodeShareLink(payload).entries).toHaveLength(500);
  });

  test.each([0, 1.5, 2147483648, Number.NaN, -1])("throws RangeError for id %s", (id) => {
    expect(() => encodeShareLink(finished([[1, false]]), id)).toThrow(RangeError);
  });

  test("throws RangeError for no Statements or more than 500", () => {
    expect(() => encodeShareLink(finished([]), 1)).toThrow(RangeError);
    const tooMany = finished(Array.from({ length: 501 }, () => [1, false] as const));
    expect(() => encodeShareLink(tooMany, 1)).toThrow(RangeError);
  });

  test("throws RangeError when a Statement has no Answer", () => {
    const state = finished([[1, false], [2, false]]);
    const answers = new Map(state.answers);
    answers.delete(102);
    expect(() => encodeShareLink({ ...state, answers }, 1)).toThrow(RangeError);
  });

  test("every character is RFC 3986 unreserved", () => {
    const payload = encodeShareLink(finished([[2, true], [SKIP, false]]), 42);
    expect(encodeURIComponent(payload)).toBe(payload);
  });
});

describe("decodeShareLink", () => {
  test("decodes values and Important flags in order", () => {
    expect(decodeShareLink("v1-12-aBcDeSs")).toEqual({
      formatVersion: 1,
      datasetVersionId: 12,
      entries: [
        { value: -2, important: false },
        { value: -1, important: true },
        { value: 0, important: false },
        { value: 1, important: true },
        { value: 2, important: false },
        { value: SKIP, important: true },
        { value: SKIP, important: false },
      ],
    });
  });

  test.each([
    "",
    "v1",
    "v1-1-",
    "v1-0-a",
    "v1-01-a",
    "v1-2147483648-a",
    "v1-9999999999-a",
    "v1-1-f",
    "v1-1-a b",
    "V1-1-a",
    "v1-1-a-",
    "#v1-1-a",
    "v1-1-%61",
    "v0-1-a",
    " v1-1-a",
    "v1-1-a\n",
    "v1--1-a",
    `v1-1-${"a".repeat(501)}`,
    `v1-1-${"a".repeat(1019)}`,
  ])("malformed: %j", (fragment) => {
    expectError(() => decodeShareLink(fragment), "malformed");
  });

  test("a 1025-character string is malformed before any pattern check", () => {
    expectError(() => decodeShareLink(`v2-${"a".repeat(1022)}`), "malformed");
  });

  test.each(["v2-1-a", "v10-1-a", "v999-1-zzz"])("unsupported_version: %s", (fragment) => {
    expectError(() => decodeShareLink(fragment), "unsupported_version");
  });
});

describe("restoreQuestionnaire", () => {
  const ids = [101, 102, 103];

  test("returns the end-screen state with answers and flags by Statement id", () => {
    const state = restoreQuestionnaire(decodeShareLink("v1-1-dSa"), ids);
    expect(state.currentIndex).toBe(3);
    expect(state.statementIds).toEqual(ids);
    expect([...state.answers]).toEqual([
      [101, 1],
      [102, SKIP],
      [103, -2],
    ]);
    expect([...state.important]).toEqual([102]);
  });

  test("statement_count_mismatch for one id too few or too many", () => {
    const link = decodeShareLink("v1-1-dSa");
    expectError(() => restoreQuestionnaire(link, ids.slice(0, 2)), "statement_count_mismatch");
    expectError(() => restoreQuestionnaire(link, [...ids, 104]), "statement_count_mismatch");
  });

  test("Scenario 2: skip and Important round-trip with identical ranking", () => {
    const sixIds = [101, 102, 103, 104, 105, 106];
    const live = finished(
      [
        [1, false],
        [SKIP, true],
        [1, false],
        [1, false],
        [1, false],
        [SKIP, false],
      ],
      sixIds,
    );
    const payload = encodeShareLink(live, 1);
    expect(payload).toBe("v1-1-dSddds");
    const restored = restoreQuestionnaire(decodeShareLink(payload), sixIds);
    expect(restored.answers).toEqual(live.answers);
    expect(restored.important).toEqual(live.important);
    const parties = partiesFor(sixIds, prng(7));
    expect(rankParties(toMatchScoreAnswers(restored), parties)).toEqual(
      rankParties(toMatchScoreAnswers(live), parties),
    );
  });

  test("random round-trips are lossless and rank identically (seeded, 200 cases)", () => {
    const random = prng(20261020);
    for (let n = 0; n < 200; n += 1) {
      const count = 1 + Math.floor(random() * 60);
      const ids = Array.from({ length: count }, (_, i) => 1000 + i * 3 + Math.floor(random() * 3));
      const entries = ids.map(
        () => [VALUES[Math.floor(random() * VALUES.length)]!, random() < 0.3] as const,
      );
      const live = finished(entries, ids);
      const versionId = 1 + Math.floor(random() * 2147483647);
      const link = decodeShareLink(encodeShareLink(live, versionId));
      expect(link.datasetVersionId).toBe(versionId);
      const restored = restoreQuestionnaire(link, ids);
      expect(restored.answers).toEqual(live.answers);
      expect(restored.important).toEqual(live.important);
      expect(restored.currentIndex).toBe(ids.length);
      const parties = partiesFor(ids, random);
      expect(rankParties(toMatchScoreAnswers(restored), parties)).toEqual(
        rankParties(toMatchScoreAnswers(live), parties),
      );
    }
  });
});
