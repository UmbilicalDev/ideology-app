import { describe, expect, test, vi } from "vitest";

import {
  PublicApiError,
  createPublicApiClient,
  type FetchLike,
  type HttpResponseLike,
} from "../../src/index";

function jsonResponse(body: unknown, status = 200): HttpResponseLike & { json: ReturnType<typeof vi.fn> } {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn(async () => body),
  };
}

function electionBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    country: "ES",
    type: "general",
    date: "2023-07-23",
    name: "Generales 2023",
    status: "active",
    published_dataset_version_id: 1,
    ...overrides,
  };
}

function fetchReturning(response: HttpResponseLike) {
  return vi.fn<FetchLike>(async () => response);
}

async function listError(fetch: FetchLike): Promise<PublicApiError> {
  const api = createPublicApiClient({ fetch });
  const error: unknown = await api.listElections().then(
    () => {
      throw new Error("expected listElections to reject");
    },
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(PublicApiError);
  return error as PublicApiError;
}

describe("createPublicApiClient listElections", () => {
  test("sends exactly one GET to /api/v1/elections with an Accept header", async () => {
    const fetch = fetchReturning(jsonResponse({ elections: [] }));
    await createPublicApiClient({ fetch }).listElections();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/elections", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("prefixes baseUrl and trims one trailing slash", async () => {
    const fetch = fetchReturning(jsonResponse({ elections: [] }));
    await createPublicApiClient({ fetch, baseUrl: "http://h/" }).listElections();
    expect(fetch.mock.calls[0]?.[0]).toBe("http://h/api/v1/elections");
  });

  test("calls fetch as a plain function, not as a method of options", async () => {
    let receiver: unknown = "unset";
    const fetch: FetchLike = function (this: unknown) {
      receiver = this;
      return Promise.resolve(jsonResponse({ elections: [] }));
    };
    await createPublicApiClient({ fetch }).listElections();
    expect(receiver).toBeUndefined();
  });

  test("maps snake_case to camelCase and keeps the API order", async () => {
    const fetch = fetchReturning(
      jsonResponse({
        elections: [
          electionBody({ id: 3, date: "2027-07-01", name: "Generales 2027", published_dataset_version_id: 5 }),
          electionBody(),
        ],
      }),
    );
    const elections = await createPublicApiClient({ fetch }).listElections();
    expect(elections).toEqual([
      {
        id: 3,
        country: "ES",
        type: "general",
        date: "2027-07-01",
        name: "Generales 2027",
        status: "active",
        publishedDatasetVersionId: 5,
      },
      {
        id: 1,
        country: "ES",
        type: "general",
        date: "2023-07-23",
        name: "Generales 2023",
        status: "active",
        publishedDatasetVersionId: 1,
      },
    ]);
  });

  test("accepts a null published_dataset_version_id", async () => {
    const fetch = fetchReturning(
      jsonResponse({ elections: [electionBody({ published_dataset_version_id: null })] }),
    );
    const [election] = await createPublicApiClient({ fetch }).listElections();
    expect(election?.publishedDatasetVersionId).toBeNull();
  });

  test("ignores unknown keys in the body and in items", async () => {
    const fetch = fetchReturning(
      jsonResponse({ elections: [electionBody({ extra: "x" })], next: null }),
    );
    const elections = await createPublicApiClient({ fetch }).listElections();
    expect(elections).toHaveLength(1);
    expect(Object.keys(elections[0] ?? {}).sort()).toEqual([
      "country",
      "date",
      "id",
      "name",
      "publishedDatasetVersionId",
      "status",
      "type",
    ]);
  });

  test("a rejected fetch is a network error", async () => {
    const fetch = vi.fn<FetchLike>(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = await listError(fetch);
    expect(error.kind).toBe("network");
    expect(error.status).toBeNull();
    expect(error.name).toBe("PublicApiError");
  });

  test("a non-ok response is an http error and json() is not called", async () => {
    const response = jsonResponse("Internal Server Error", 500);
    const error = await listError(fetchReturning(response));
    expect(error.kind).toBe("http");
    expect(error.status).toBe(500);
    expect(response.json).not.toHaveBeenCalled();
  });

  test("a rejected json() is an invalid response", async () => {
    const response: HttpResponseLike = {
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token")),
    };
    const error = await listError(fetchReturning(response));
    expect(error.kind).toBe("invalid_response");
    expect(error.status).toBeNull();
  });

  test.each([
    ["a non-object body", [], "response body must be an object"],
    ["a null body", null, "response body must be an object"],
    ["a missing elections key", {}, "elections must be an array"],
    ["a non-array elections", { elections: {} }, "elections must be an array"],
    ["an item that is not an object", { elections: ["x"] }, "elections[0] must be an object"],
    ["id 0", { elections: [electionBody({ id: 0 })] }, "elections[0].id must be a positive integer"],
    ["id 1.5", { elections: [electionBody({ id: 1.5 })] }, "elections[0].id must be a positive integer"],
    ['id "1"', { elections: [electionBody({ id: "1" })] }, "elections[0].id must be a positive integer"],
    ["name 7", { elections: [electionBody({ name: 7 })] }, "elections[0].name must be a string"],
    ["a missing country", { elections: [electionBody({ country: undefined })] }, "elections[0].country must be a string"],
    ["type null", { elections: [electionBody({ type: null })] }, "elections[0].type must be a string"],
    ["date 23/07/2023", { elections: [electionBody({ date: "23/07/2023" })] }, "elections[0].date must be YYYY-MM-DD"],
    ["status closed", { elections: [electionBody({ status: "closed" })] }, "elections[0].status must be one of"],
    [
      'published id "1"',
      { elections: [electionBody({ published_dataset_version_id: "1" })] },
      "elections[0].published_dataset_version_id must be null or a positive integer",
    ],
    [
      "a bad second item",
      { elections: [electionBody(), electionBody({ date: "2023-7-23" })] },
      "elections[1].date must be YYYY-MM-DD",
    ],
  ])("%s is an invalid response naming the field", async (_label, body, message) => {
    const error = await listError(fetchReturning(jsonResponse(body)));
    expect(error.kind).toBe("invalid_response");
    expect(error.status).toBeNull();
    expect(error.message).toContain(message);
  });
});

async function rejection(promise: Promise<unknown>): Promise<PublicApiError> {
  const error: unknown = await promise.then(
    () => {
      throw new Error("expected the call to reject");
    },
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(PublicApiError);
  return error as PublicApiError;
}

describe("createPublicApiClient getElection", () => {
  test("sends exactly one GET to /api/v1/elections/{id} with an Accept header", async () => {
    const fetch = fetchReturning(jsonResponse(electionBody({ id: 7 })));
    await createPublicApiClient({ fetch }).getElection(7);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/elections/7", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("prefixes baseUrl", async () => {
    const fetch = fetchReturning(jsonResponse(electionBody({ id: 7 })));
    await createPublicApiClient({ fetch, baseUrl: "http://h/" }).getElection(7);
    expect(fetch.mock.calls[0]?.[0]).toBe("http://h/api/v1/elections/7");
  });

  test("maps a draft Election with no Published version to camelCase", async () => {
    const fetch = fetchReturning(
      jsonResponse(electionBody({ id: 2, status: "draft", published_dataset_version_id: null })),
    );
    expect(await createPublicApiClient({ fetch }).getElection(2)).toEqual({
      id: 2,
      country: "ES",
      type: "general",
      date: "2023-07-23",
      name: "Generales 2023",
      status: "draft",
      publishedDatasetVersionId: null,
    });
  });

  test("a 404 is an http error with status 404 and json() is not called", async () => {
    const response = jsonResponse({ error: { code: "election_not_found", message: "x" } }, 404);
    const error = await rejection(createPublicApiClient({ fetch: fetchReturning(response) }).getElection(9));
    expect(error.kind).toBe("http");
    expect(error.status).toBe(404);
    expect(response.json).not.toHaveBeenCalled();
  });

  test("a contract violation names the path and the field", async () => {
    const fetch = fetchReturning(jsonResponse(electionBody({ date: "x" })));
    const error = await rejection(createPublicApiClient({ fetch }).getElection(1));
    expect(error.kind).toBe("invalid_response");
    expect(error.message).toBe("GET /api/v1/elections/1: election.date must be YYYY-MM-DD");
  });
});

function evidenceBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    quote: "Una cita literal.",
    page: 4,
    url: "https://example.org/programa.pdf",
    source_document_id: 2,
    ...overrides,
  };
}

const LOGO_URL = "/api/v1/parties/5/logo?v=0123456789abcdef";

function versionBody(): Record<string, unknown> {
  return {
    id: 3,
    election_id: 1,
    created_at: "2026-10-20T09:30:00Z",
    statements: [
      { id: 10, position: 1, text: "Afirmación uno", topic: "economía" },
      { id: 20, position: 2, text: "Afirmación dos", topic: "vivienda" },
    ],
    parties: [
      {
        id: 5,
        name: "Partido A",
        short_name: "PA",
        logo_url: LOGO_URL,
        positions: [
          { statement_id: 10, value: 2, evidence: evidenceBody() },
          { statement_id: 20, value: "no_stance", evidence: null },
        ],
      },
    ],
  };
}

type Mutate = (body: Record<string, any>) => void;

function mutated(mutate: Mutate): Record<string, unknown> {
  const body = versionBody() as Record<string, any>;
  mutate(body);
  return body;
}

describe("createPublicApiClient getDatasetVersion", () => {
  test("sends exactly one GET to /api/v1/dataset-versions/{id} with an Accept header", async () => {
    const fetch = fetchReturning(jsonResponse(versionBody()));
    await createPublicApiClient({ fetch }).getDatasetVersion(3);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/dataset-versions/3", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("prefixes baseUrl", async () => {
    const fetch = fetchReturning(jsonResponse(versionBody()));
    await createPublicApiClient({ fetch, baseUrl: "http://h" }).getDatasetVersion(3);
    expect(fetch.mock.calls[0]?.[0]).toBe("http://h/api/v1/dataset-versions/3");
  });

  test("maps the body to camelCase and ignores unknown keys", async () => {
    const body = mutated((b) => {
      b["extra"] = true;
      b["statements"][0]["extra"] = 1;
      b["parties"][0]["positions"][0]["evidence"]["extra"] = "x";
    });
    const version = await createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) }).getDatasetVersion(3);
    expect(version).toEqual({
      id: 3,
      electionId: 1,
      createdAt: "2026-10-20T09:30:00Z",
      statements: [
        { id: 10, position: 1, text: "Afirmación uno", topic: "economía" },
        { id: 20, position: 2, text: "Afirmación dos", topic: "vivienda" },
      ],
      parties: [
        {
          id: 5,
          name: "Partido A",
          shortName: "PA",
          logoUrl: LOGO_URL,
          positions: [
            {
              statementId: 10,
              value: 2,
              evidence: {
                quote: "Una cita literal.",
                page: 4,
                url: "https://example.org/programa.pdf",
                sourceDocumentId: 2,
              },
            },
            { statementId: 20, value: "no_stance", evidence: null },
          ],
        },
      ],
    });
  });

  test("accepts a null evidence url, zero Statements and zero Parties", async () => {
    const withNullUrl = mutated((b) => {
      b["parties"][0]["positions"][0]["evidence"]["url"] = null;
    });
    const api = createPublicApiClient({ fetch: fetchReturning(jsonResponse(withNullUrl)) });
    const version = await api.getDatasetVersion(3);
    expect(version.parties[0]?.positions[0]?.evidence?.url).toBeNull();

    const empty = { ...versionBody(), statements: [], parties: [] };
    const emptyVersion = await createPublicApiClient({ fetch: fetchReturning(jsonResponse(empty)) }).getDatasetVersion(3);
    expect(emptyVersion.statements).toEqual([]);
    expect(emptyVersion.parties).toEqual([]);
  });

  test("a null or missing logo_url is null (bodies cached before logo_url existed)", async () => {
    const mutations: Mutate[] = [
      (b) => { b["parties"][0]["logo_url"] = null; },
      (b) => { delete b["parties"][0]["logo_url"]; },
    ];
    for (const mutate of mutations) {
      const api = createPublicApiClient({ fetch: fetchReturning(jsonResponse(mutated(mutate))) });
      const version = await api.getDatasetVersion(3);
      expect(version.parties[0]?.logoUrl).toBeNull();
    }
  });

  test("a 404 is an http error with status 404 and json() is not called", async () => {
    const response = jsonResponse({ error: { code: "dataset_version_not_found", message: "x" } }, 404);
    const error = await rejection(
      createPublicApiClient({ fetch: fetchReturning(response) }).getDatasetVersion(3),
    );
    expect(error.kind).toBe("http");
    expect(error.status).toBe(404);
    expect(response.json).not.toHaveBeenCalled();
  });

  test("a rejected fetch is a network error", async () => {
    const fetch = vi.fn<FetchLike>(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = await rejection(createPublicApiClient({ fetch }).getDatasetVersion(3));
    expect(error.kind).toBe("network");
    expect(error.status).toBeNull();
  });

  test("a body that is not JSON is an invalid response", async () => {
    const response: HttpResponseLike = {
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token")),
    };
    const error = await rejection(createPublicApiClient({ fetch: fetchReturning(response) }).getDatasetVersion(3));
    expect(error.kind).toBe("invalid_response");
  });

  test.each<[string, Mutate, string]>([
    ["id 0", (b) => { b["id"] = 0; }, "dataset_version.id must be a positive integer"],
    ['election_id "1"', (b) => { b["election_id"] = "1"; }, "dataset_version.election_id must be a positive integer"],
    ["a bad created_at", (b) => { b["created_at"] = "2026-10-20 09:30:00"; }, "dataset_version.created_at must be YYYY-MM-DDTHH:MM:SSZ"],
    ["a missing statements", (b) => { delete b["statements"]; }, "dataset_version.statements must be an array"],
    ["a missing parties", (b) => { delete b["parties"]; }, "dataset_version.parties must be an array"],
    ["a statement that is not an object", (b) => { b["statements"][1] = "x"; }, "statements[1] must be an object"],
    ["a duplicate statement id", (b) => { b["statements"][1]["id"] = 10; }, "statements[1].id 10 is a duplicate"],
    ["position 0", (b) => { b["statements"][0]["position"] = 0; }, "statements[0].position must be a positive integer"],
    ["a non-increasing position", (b) => { b["statements"][1]["position"] = 1; }, "statements[1].position must be greater than the previous position"],
    ["text null", (b) => { b["statements"][0]["text"] = null; }, "statements[0].text must be a string"],
    ["a missing topic", (b) => { delete b["statements"][0]["topic"]; }, "statements[0].topic must be a string"],
    ["party id 1.5", (b) => { b["parties"][0]["id"] = 1.5; }, "parties[0].id must be a positive integer"],
    ["a missing short_name", (b) => { delete b["parties"][0]["short_name"]; }, "parties[0].short_name must be a string"],
    ...[
      "https://evil.example/logo.png",
      "//evil.example/api/v1/parties/5/logo?v=0123456789abcdef",
      "http://localhost/api/v1/parties/5/logo?v=0123456789abcdef",
      "/api/v1/parties/5/logo",
      "/api/v1/parties/0/logo?v=0123456789abcdef",
      "/api/v1/parties/5/logo?v=0123456789ABCDEF",
      "/api/v1/parties/5/logo?v=0123456789abcdef&x=1",
      "data:image/png;base64,AAAA",
      "",
    ].map((url): [string, Mutate, string] => [
      `logo_url ${JSON.stringify(url)}`,
      (b) => { b["parties"][0]["logo_url"] = url; },
      "parties[0].logo_url must be null or a path like /api/v1/parties/{id}/logo?v=<16 hex>",
    ]),
    ["logo_url 7", (b) => { b["parties"][0]["logo_url"] = 7; }, "parties[0].logo_url must be null or a path"],
    ["a positions length mismatch", (b) => { b["parties"][0]["positions"].pop(); }, "parties[0].positions must have one entry per Statement (2), got 1"],
    ["a wrong statement_id order", (b) => { b["parties"][0]["positions"].reverse(); }, "parties[0].positions[0].statement_id must be 10"],
    ["value 3", (b) => { b["parties"][0]["positions"][0]["value"] = 3; }, 'parties[0].positions[0].value must be an integer from -2 to 2 or "no_stance"'],
    ['value "2"', (b) => { b["parties"][0]["positions"][0]["value"] = "2"; }, 'parties[0].positions[0].value must be an integer from -2 to 2 or "no_stance"'],
    ["value 0.5", (b) => { b["parties"][0]["positions"][0]["value"] = 0.5; }, 'parties[0].positions[0].value must be an integer from -2 to 2 or "no_stance"'],
    ["evidence null with a value", (b) => { b["parties"][0]["positions"][0]["evidence"] = null; }, 'parties[0].positions[0].evidence must not be null when value is not "no_stance"'],
    ["evidence present with no_stance", (b) => { b["parties"][0]["positions"][1]["evidence"] = evidenceBody(); }, 'parties[0].positions[1].evidence must be null when value is "no_stance"'],
    ["evidence page 0", (b) => { b["parties"][0]["positions"][0]["evidence"]["page"] = 0; }, "parties[0].positions[0].evidence.page must be a positive integer"],
    ["evidence url 7", (b) => { b["parties"][0]["positions"][0]["evidence"]["url"] = 7; }, "parties[0].positions[0].evidence.url must be null or a string"],
    ["a missing quote", (b) => { delete b["parties"][0]["positions"][0]["evidence"]["quote"]; }, "parties[0].positions[0].evidence.quote must be a string"],
    ["source_document_id -1", (b) => { b["parties"][0]["positions"][0]["evidence"]["source_document_id"] = -1; }, "parties[0].positions[0].evidence.source_document_id must be a positive integer"],
  ])("%s is an invalid response naming the field", async (_label, mutate, message) => {
    const fetch = fetchReturning(jsonResponse(mutated(mutate)));
    const error = await rejection(createPublicApiClient({ fetch }).getDatasetVersion(3));
    expect(error.kind).toBe("invalid_response");
    expect(error.status).toBeNull();
    expect(error.message.startsWith(`GET /api/v1/dataset-versions/3: ${message}`)).toBe(true);
  });

  test.each([
    ["an array body", []],
    ["a null body", null],
  ])("%s is an invalid response", async (_label, body) => {
    const error = await rejection(
      createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) }).getDatasetVersion(3),
    );
    expect(error.message).toBe("GET /api/v1/dataset-versions/3: response body must be an object");
  });
});
