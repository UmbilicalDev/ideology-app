import { describe, expect, test, vi } from "vitest";

import {
  PublicApiError,
  buildResults,
  openShareLink,
  restoreQuestionnaire,
  decodeShareLink,
  type DatasetVersion,
  type Election,
  type Party,
  type PublicApi,
} from "../../src/index";

const STATEMENTS = Array.from({ length: 3 }, (_, i) => ({
  id: 101 + i,
  position: i + 1,
  text: `Afirmación ${i + 1}.`,
  topic: "economía",
}));

function party(id: number, name: string, value: 1 | -1): Party {
  return {
    id,
    name,
    shortName: `P${id}`,
    logoUrl: null,
    positions: STATEMENTS.map((s) => ({
      statementId: s.id,
      value,
      evidence: { quote: "Cita.", page: 1, url: null, sourceDocumentId: id },
    })),
  };
}

const VERSION: DatasetVersion = {
  id: 7,
  electionId: 3,
  createdAt: "2026-10-20T09:30:00Z",
  statements: STATEMENTS,
  parties: [party(1, "Uno", 1), party(2, "Dos", -1)],
};

const ELECTION: Election = {
  id: 3,
  country: "ES",
  type: "general",
  date: "2023-07-23",
  name: "Generales 2023",
  status: "active",
  publishedDatasetVersionId: 7,
};

const LINK = "v1-7-dsA";

function fakeApi({
  version = async () => VERSION,
  election = async () => ELECTION,
}: {
  readonly version?: (id: number) => Promise<DatasetVersion>;
  readonly election?: (id: number) => Promise<Election>;
} = {}) {
  const getDatasetVersion = vi.fn(version);
  const getElection = vi.fn(election);
  const listElections = vi.fn(async () => [] as readonly Election[]);
  const api: PublicApi = { getDatasetVersion, getElection, listElections };
  return { api, getDatasetVersion, getElection, listElections };
}

const http = (status: number) => new PublicApiError("http", `GET: ${status}`, status);

describe("openShareLink", () => {
  test("ready: one request each, restored state and buildResults output", async () => {
    const fake = fakeApi();
    const result = await openShareLink(fake.api, LINK);
    expect(fake.getDatasetVersion.mock.calls).toEqual([[7]]);
    expect(fake.getElection.mock.calls).toEqual([[3]]);
    expect(fake.listElections).not.toHaveBeenCalled();
    const state = restoreQuestionnaire(decodeShareLink(LINK), [101, 102, 103]);
    expect(result).toEqual({
      kind: "ready",
      election: ELECTION,
      datasetVersion: VERSION,
      state,
      results: buildResults(VERSION, state),
      versionStatus: "current",
      questionnaireAvailable: true,
    });
  });

  test.each([
    [{ publishedDatasetVersionId: 8 }, "superseded", true],
    [{ publishedDatasetVersionId: null }, "no_current", false],
    [{ status: "archived" as const, publishedDatasetVersionId: 8 }, "superseded", false],
    [{ status: "archived" as const }, "current", false],
  ])("Election %o → %s, questionnaireAvailable %s", async (overrides, status, available) => {
    const fake = fakeApi({ election: async () => ({ ...ELECTION, ...overrides }) });
    const result = await openShareLink(fake.api, LINK);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    expect(result.versionStatus).toBe(status);
    expect(result.questionnaireAvailable).toBe(available);
  });

  test("an empty fragment is missing, with no request", async () => {
    const fake = fakeApi();
    expect(await openShareLink(fake.api, "")).toEqual({ kind: "missing" });
    expect(fake.getDatasetVersion).not.toHaveBeenCalled();
  });

  test.each([
    ["v1-7-dsf", "malformed"],
    ["garbage", "malformed"],
    ["V1-7-a", "malformed"],
    ["v1-7-" + "d".repeat(1020), "malformed"],
    ["v2-7-a", "unsupported_version"],
  ])("%s is invalid (%s) with no request", async (fragment, reason) => {
    const fake = fakeApi();
    expect(await openShareLink(fake.api, fragment)).toEqual({ kind: "invalid", reason });
    expect(fake.getDatasetVersion).not.toHaveBeenCalled();
    expect(fake.getElection).not.toHaveBeenCalled();
  });

  test.each(["v1-7-ds", "v1-7-dsAd"])(
    "%s has the wrong letter count: invalid after exactly one request",
    async (fragment) => {
      const fake = fakeApi();
      expect(await openShareLink(fake.api, fragment)).toEqual({
        kind: "invalid",
        reason: "statement_count_mismatch",
      });
      expect(fake.getDatasetVersion).toHaveBeenCalledTimes(1);
      expect(fake.getElection).not.toHaveBeenCalled();
    },
  );

  test("a Dataset Version 404 is not_found after one request", async () => {
    const fake = fakeApi({ version: async () => Promise.reject(http(404)) });
    expect(await openShareLink(fake.api, LINK)).toEqual({ kind: "not_found" });
    expect(fake.getDatasetVersion).toHaveBeenCalledTimes(1);
    expect(fake.getElection).not.toHaveBeenCalled();
  });

  test("an Election 404 is not_found", async () => {
    const fake = fakeApi({ election: async () => Promise.reject(http(404)) });
    expect(await openShareLink(fake.api, LINK)).toEqual({ kind: "not_found" });
    expect(fake.getElection).toHaveBeenCalledTimes(1);
  });

  const failures: [string, () => Promise<never>][] = [
    ["network", () => Promise.reject(new PublicApiError("network", "offline"))],
    ["http 500", () => Promise.reject(http(500))],
    ["invalid_response", () => Promise.reject(new PublicApiError("invalid_response", "bad body"))],
    ["a plain Error", () => Promise.reject(new Error("boom"))],
  ];

  test.each(failures)("a Dataset Version %s failure is error", async (_name, fail) => {
    const fake = fakeApi({ version: fail });
    expect(await openShareLink(fake.api, LINK)).toEqual({ kind: "error" });
    expect(fake.getElection).not.toHaveBeenCalled();
  });

  test.each(failures)("an Election %s failure is error", async (_name, fail) => {
    const fake = fakeApi({ election: fail });
    expect(await openShareLink(fake.api, LINK)).toEqual({ kind: "error" });
  });

  test("a Dataset Version with another id is error, without an Election request", async () => {
    const fake = fakeApi({ version: async () => ({ ...VERSION, id: 8 }) });
    expect(await openShareLink(fake.api, LINK)).toEqual({ kind: "error" });
    expect(fake.getElection).not.toHaveBeenCalled();
  });

  test("an Election with another id is error", async () => {
    const fake = fakeApi({ election: async () => ({ ...ELECTION, id: 4 }) });
    expect(await openShareLink(fake.api, LINK)).toEqual({ kind: "error" });
  });

  test("an engine error (a Position with an invalid value) is error", async () => {
    const broken: DatasetVersion = {
      ...VERSION,
      parties: [
        {
          ...VERSION.parties[0]!,
          positions: VERSION.parties[0]!.positions.map((p) => ({ ...p, value: 9 as unknown as 1 })),
        },
      ],
    };
    const fake = fakeApi({ version: async () => broken });
    expect(await openShareLink(fake.api, LINK)).toEqual({ kind: "error" });
  });

  test("nothing is logged", async () => {
    // Core has no DOM or Node types (`types: []`), so `console` is reached structurally.
    const logger = (globalThis as unknown as { console: Record<string, (...args: unknown[]) => void> })
      .console;
    const spies = ["error", "warn", "log", "info", "debug"].map((m) =>
      vi.spyOn(logger, m).mockImplementation(() => undefined),
    );
    try {
      await openShareLink(fakeApi({ version: async () => Promise.reject(http(500)) }).api, LINK);
      await openShareLink(fakeApi().api, "garbage");
      await openShareLink(fakeApi().api, LINK);
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    } finally {
      for (const spy of spies) spy.mockRestore();
    }
  });
});
