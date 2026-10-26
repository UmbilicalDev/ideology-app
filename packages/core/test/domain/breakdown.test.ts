import { describe, expect, test } from "vitest";

import {
  NO_STANCE,
  SKIP,
  buildBreakdown,
  evidenceHref,
  rankParties,
  type Answer,
  type Party,
  type PartyPosition,
  type ScaleValue,
  type Statement,
} from "../../src/index";

const STATEMENTS: Statement[] = [
  { id: 11, position: 1, text: "Primera afirmación.", topic: "economía" },
  { id: 12, position: 2, text: "Segunda afirmación.", topic: "vivienda" },
  { id: 13, position: 3, text: "Tercera afirmación.", topic: "energía" },
];

function party(
  id: number,
  name: string,
  values: readonly (ScaleValue | typeof NO_STANCE)[],
  url: string | null = null,
): Party {
  const positions: PartyPosition[] = values.map((value, i) => ({
    statementId: STATEMENTS[i]!.id,
    value,
    evidence:
      value === NO_STANCE
        ? null
        : { quote: `Cita ${name} ${i + 1}.`, page: i + 1, url, sourceDocumentId: id },
  }));
  return { id, name, shortName: `P${id}`, logoUrl: null, positions };
}

const PARTIES: Party[] = [
  party(1, "Alfa", [1, 1, 1]),
  party(2, "Beta", [-1, NO_STANCE, -2], "https://example.org/beta.pdf"),
  party(3, "Gamma", [2, 0, NO_STANCE]),
];

function names(row: { readonly positions: readonly { readonly name: string }[] }): string[] {
  return row.positions.map((p) => p.name);
}

describe("buildBreakdown", () => {
  test("rows follow Statement order with id, position and text", () => {
    const rows = buildBreakdown(STATEMENTS, PARTIES, [], [1, 2, 3]);
    expect(rows.map((r) => [r.statementId, r.position, r.text])).toEqual([
      [11, 1, "Primera afirmación."],
      [12, 2, "Segunda afirmación."],
      [13, 3, "Tercera afirmación."],
    ]);
  });

  test("answers: rating, skip and missing; important only for a rated flagged Answer", () => {
    const answers: Answer[] = [
      { statementId: 11, value: 2, important: true },
      { statementId: 12, value: SKIP, important: true },
    ];
    const rows = buildBreakdown(STATEMENTS, PARTIES, answers, []);
    expect(rows.map((r) => [r.answer, r.important])).toEqual([
      [2, true],
      [SKIP, false],
      [null, false],
    ]);
    const unflagged = buildBreakdown(STATEMENTS, PARTIES, [{ statementId: 11, value: -1 }], []);
    expect(unflagged[0]!.important).toBe(false);
    expect(unflagged[0]!.answer).toBe(-1);
  });

  test("string Statement ids match, as in the engine", () => {
    const rows = buildBreakdown(STATEMENTS, PARTIES, [{ statementId: "13", value: 0, important: true }], []);
    expect(rows[2]!.answer).toBe(0);
    expect(rows[2]!.important).toBe(true);
  });

  test("partyOrder is used in every row; unknown ids ignored, missing ids appended in input order", () => {
    const rows = buildBreakdown(STATEMENTS, PARTIES, [], [3, 99, 1, 2]);
    for (const row of rows) {
      expect(names(row)).toEqual(["Gamma", "Alfa", "Beta"]);
    }
    const partial = buildBreakdown(STATEMENTS, PARTIES, [], [2]);
    for (const row of partial) {
      expect(names(row)).toEqual(["Beta", "Alfa", "Gamma"]);
    }
    expect(names(buildBreakdown(STATEMENTS, PARTIES, [], [])[0]!)).toEqual(["Alfa", "Beta", "Gamma"]);
  });

  test("the order equals rankParties for a fixture", () => {
    const answers: Answer[] = [
      { statementId: 11, value: -2, important: false },
      { statementId: 12, value: -1, important: true },
      { statementId: 13, value: -2, important: false },
    ];
    const order = rankParties(answers, PARTIES).map((p) => p.partyId);
    expect(order).toEqual([2, 3, 1]);
    const rows = buildBreakdown(STATEMENTS, PARTIES, answers, order);
    for (const row of rows) {
      expect(row.positions.map((p) => p.partyId)).toEqual(order);
    }
  });

  test("positions carry value and Evidence; no_stance and a missing Position have no Evidence", () => {
    const short: Party = { ...party(4, "Delta", [1, 1, 1]), positions: [] };
    const rows = buildBreakdown(STATEMENTS, [...PARTIES, short], [], [1, 2, 3, 4]);
    expect(rows[0]!.positions[0]).toEqual({
      partyId: 1,
      name: "Alfa",
      shortName: "P1",
      logoUrl: null,
      value: 1,
      evidence: { quote: "Cita Alfa 1.", page: 1, href: null },
    });
    expect(rows[0]!.positions[1]!.evidence).toEqual({
      quote: "Cita Beta 1.",
      page: 1,
      href: "https://example.org/beta.pdf#page=1",
    });
    expect(rows[1]!.positions[1]).toEqual({
      partyId: 2,
      name: "Beta",
      shortName: "P2",
      logoUrl: null,
      value: NO_STANCE,
      evidence: null,
    });
    for (const row of rows) {
      expect(row.positions[3]).toMatchObject({ partyId: 4, value: NO_STANCE, evidence: null });
    }
  });

  test("every position copies its Party's logoUrl, null or not", () => {
    const logo = "/api/v1/parties/2/logo?v=fedcba9876543210";
    const parties = PARTIES.map((p) => (p.id === 2 ? { ...p, logoUrl: logo } : p));
    const rows = buildBreakdown(STATEMENTS, parties, [], [1, 2, 3]);
    for (const row of rows) {
      expect(row.positions.map((p) => p.logoUrl)).toEqual([null, logo, null]);
    }
  });

  test("inputs are not mutated", () => {
    const answers: Answer[] = [{ statementId: 11, value: 1, important: true }];
    const order = [3, 2, 1];
    const inputs = { statements: STATEMENTS, parties: PARTIES, answers, order };
    const snapshot = JSON.parse(JSON.stringify(inputs)) as unknown;
    buildBreakdown(STATEMENTS, PARTIES, answers, order);
    expect(inputs).toEqual(snapshot);
    expect(order).toEqual([3, 2, 1]);
  });
});

describe("evidenceHref", () => {
  test("null url gives null", () => {
    expect(evidenceHref({ url: null, page: 3 })).toBeNull();
  });

  test("http(s) URL gets #page=N", () => {
    expect(evidenceHref({ url: "https://x.org/a.pdf", page: 3 })).toBe("https://x.org/a.pdf#page=3");
    expect(evidenceHref({ url: "HTTP://X.ORG/a.pdf", page: 1 })).toBe("HTTP://X.ORG/a.pdf#page=1");
  });

  test("an existing fragment is replaced and the query kept", () => {
    expect(evidenceHref({ url: "https://x.org/a.pdf#frag", page: 2 })).toBe("https://x.org/a.pdf#page=2");
    expect(evidenceHref({ url: "https://x.org/a.pdf?v=1&x=2#page=9", page: 4 })).toBe(
      "https://x.org/a.pdf?v=1&x=2#page=4",
    );
  });

  test("surrounding whitespace is trimmed", () => {
    expect(evidenceHref({ url: "  https://x.org/a.pdf\n", page: 5 })).toBe("https://x.org/a.pdf#page=5");
  });

  test.each([
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "ftp://x.org/a.pdf",
    "/relative.pdf",
    "x.org/a.pdf",
    "",
    "https://",
    "https://x.org/a b.pdf",
    "data:application/pdf;base64,AAAA",
  ])("rejects %j", (url) => {
    expect(evidenceHref({ url, page: 1 })).toBeNull();
  });
});
