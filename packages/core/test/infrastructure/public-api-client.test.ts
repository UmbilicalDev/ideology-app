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
        publishedDatasetVersionGeneration: "legacy",
      },
      {
        id: 1,
        country: "ES",
        type: "general",
        date: "2023-07-23",
        name: "Generales 2023",
        status: "active",
        publishedDatasetVersionId: 1,
        publishedDatasetVersionGeneration: "legacy",
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
      "publishedDatasetVersionGeneration",
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
      publishedDatasetVersionGeneration: null,
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
// Kept exactly as sent, surrounding whitespace included (never trimmed).
const NOTE = "  La CIE es el centro de internamiento de extranjeros. \n";

function versionBody(): Record<string, unknown> {
  return {
    id: 3,
    election_id: 1,
    created_at: "2026-10-20T09:30:00Z",
    statements: [
      { id: 10, position: 1, text: "Afirmación uno", topic: "economía", context_note: NOTE },
      { id: 20, position: 2, text: "Afirmación dos", topic: "vivienda", context_note: null },
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
    questionnaire_lengths: [1, 2],
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
        { id: 10, position: 1, text: "Afirmación uno", topic: "economía", contextNote: NOTE },
        { id: 20, position: 2, text: "Afirmación dos", topic: "vivienda", contextNote: null },
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
      questionnaireLengths: [1, 2],
    });
  });

  test("accepts a null evidence url, zero Statements and zero Parties", async () => {
    const withNullUrl = mutated((b) => {
      b["parties"][0]["positions"][0]["evidence"]["url"] = null;
    });
    const api = createPublicApiClient({ fetch: fetchReturning(jsonResponse(withNullUrl)) });
    const version = await api.getDatasetVersion(3);
    expect(version.parties[0]?.positions[0]?.evidence?.url).toBeNull();

    const { questionnaire_lengths: _lengths, ...withoutLengths } = versionBody();
    const empty = { ...withoutLengths, statements: [], parties: [] };
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

  test("a missing questionnaire_lengths reads as the full length (bodies before it existed)", async () => {
    const body = mutated((b) => { delete b["questionnaire_lengths"]; });
    const version = await createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) }).getDatasetVersion(3);
    expect(version.questionnaireLengths).toEqual([2]);
  });

  test("a single full length is accepted", async () => {
    const body = mutated((b) => { b["questionnaire_lengths"] = [2]; });
    const version = await createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) }).getDatasetVersion(3);
    expect(version.questionnaireLengths).toEqual([2]);
  });

  test("a null or missing context_note is null (bodies cached before context_note existed)", async () => {
    const mutations: Mutate[] = [
      (b) => { b["statements"][0]["context_note"] = null; },
      (b) => { delete b["statements"][0]["context_note"]; },
    ];
    for (const mutate of mutations) {
      const api = createPublicApiClient({ fetch: fetchReturning(jsonResponse(mutated(mutate))) });
      const version = await api.getDatasetVersion(3);
      expect(version.statements[0]?.contextNote).toBeNull();
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
    ['context_note ""', (b) => { b["statements"][0]["context_note"] = ""; }, "statements[0].context_note must be null or a non-empty string"],
    ["context_note 7", (b) => { b["statements"][1]["context_note"] = 7; }, "statements[1].context_note must be null or a non-empty string"],
    ["context_note {}", (b) => { b["statements"][0]["context_note"] = {}; }, "statements[0].context_note must be null or a non-empty string"],
    ...([
      ["null", null],
      ["[]", []],
      ["[2, 1]", [2, 1]],
      ["[1, 1, 2]", [1, 1, 2]],
      ["[0, 2]", [0, 2]],
      ["[1]", [1]],
      ["[1, 3]", [1, 3]],
      ["[1.5, 2]", [1.5, 2]],
      ['["1", 2]', ["1", 2]],
      ['"1,2"', "1,2"],
    ] as const).map(([label, value]): [string, Mutate, string] => [
      `questionnaire_lengths ${label}`,
      (b) => { b["questionnaire_lengths"] = value; },
      "dataset_version.questionnaire_lengths must be strictly increasing positive integers " +
        "ending at the statement count (2)",
    ]),
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

describe("createPublicApiClient sendFeedback", () => {
  function emptyResponse(status: number): HttpResponseLike & { json: ReturnType<typeof vi.fn> } {
    return {
      ok: status >= 200 && status < 300,
      status,
      json: vi.fn(async () => {
        throw new Error("the body must not be read");
      }),
    };
  }

  async function sendError(fetch: FetchLike): Promise<PublicApiError> {
    const error: unknown = await createPublicApiClient({ fetch })
      .sendFeedback({ message: "hola", origin: "landing" })
      .then(
        () => {
          throw new Error("expected sendFeedback to reject");
        },
        (reason: unknown) => reason,
      );
    expect(error).toBeInstanceOf(PublicApiError);
    return error as PublicApiError;
  }

  test("sends exactly one POST with the JSON body and nothing else", async () => {
    const response = emptyResponse(201);
    const fetch = fetchReturning(response);
    const result = await createPublicApiClient({ fetch }).sendFeedback({
      message: "hola",
      origin: "landing",
    });
    expect(result).toBeUndefined();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/feedback", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: '{"message":"hola","origin":"landing"}',
    });
    const init = fetch.mock.calls[0]?.[1];
    expect(JSON.parse(init?.body ?? "")).toEqual({ message: "hola", origin: "landing" });
    expect(response.json).not.toHaveBeenCalled();
  });

  test("sends the message as given; the server trims and checks it", async () => {
    const fetch = fetchReturning(emptyResponse(201));
    await createPublicApiClient({ fetch }).sendFeedback({ message: "  hola\n", origin: "results" });
    expect(JSON.parse(fetch.mock.calls[0]?.[1]?.body ?? "")).toEqual({
      message: "  hola\n",
      origin: "results",
    });
  });

  test("sends website only when it is a non-empty string", async () => {
    const fetch = fetchReturning(emptyResponse(201));
    const api = createPublicApiClient({ fetch });
    await api.sendFeedback({ message: "a", origin: "landing", website: "" });
    await api.sendFeedback({ message: "a", origin: "landing", website: "http://spam" });
    expect(JSON.parse(fetch.mock.calls[0]?.[1]?.body ?? "")).toEqual({ message: "a", origin: "landing" });
    expect(JSON.parse(fetch.mock.calls[1]?.[1]?.body ?? "")).toEqual({
      message: "a",
      origin: "landing",
      website: "http://spam",
    });
  });

  test("never sends extra keys passed at runtime", async () => {
    const fetch = fetchReturning(emptyResponse(201));
    const input = { message: "a", origin: "landing", answers: "abc", electionId: 1 } as const;
    await createPublicApiClient({ fetch }).sendFeedback(input);
    expect(JSON.parse(fetch.mock.calls[0]?.[1]?.body ?? "")).toEqual({ message: "a", origin: "landing" });
  });

  test("any 2xx resolves without reading the body", async () => {
    for (const status of [200, 201, 204]) {
      const response = emptyResponse(status);
      await expect(
        createPublicApiClient({ fetch: fetchReturning(response) }).sendFeedback({
          message: "a",
          origin: "landing",
        }),
      ).resolves.toBeUndefined();
      expect(response.json).not.toHaveBeenCalled();
    }
  });

  test.each([413, 415, 422, 429, 500])("HTTP %i rejects as http with that status", async (status) => {
    const error = await sendError(fetchReturning(emptyResponse(status)));
    expect(error.kind).toBe("http");
    expect(error.status).toBe(status);
    expect(error.message).toBe(`POST /api/v1/feedback failed: HTTP ${status}`);
  });

  test("a rejected fetch rejects as network", async () => {
    const error = await sendError(vi.fn<FetchLike>(async () => Promise.reject(new TypeError("offline"))));
    expect(error.kind).toBe("network");
    expect(error.status).toBeNull();
    expect(error.message).toBe("POST /api/v1/feedback failed: network error");
  });

  test("prefixes baseUrl, trims one trailing slash and calls fetch as a plain function", async () => {
    let receiver: unknown = "unset";
    const calls: string[] = [];
    const fetch: FetchLike = function (this: unknown, url: string) {
      receiver = this;
      calls.push(url);
      return Promise.resolve(emptyResponse(201));
    };
    await createPublicApiClient({ fetch, baseUrl: "http://h/" }).sendFeedback({
      message: "a",
      origin: "landing",
    });
    expect(calls).toEqual(["http://h/api/v1/feedback"]);
    expect(receiver).toBeUndefined();
  });
});

// legal-privacy-page: fictitious values only.
function legalNoticeBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    holders: [
      { name: "Persona Uno", nif: "00000000T" },
      { name: "Persona Dos", nif: null },
    ],
    contact_email: "contacto@ideologiapp.test",
    address: "Calle Ficticia 1",
    ...overrides,
  };
}

describe("createPublicApiClient getLegalNotice", () => {
  test("sends exactly one GET to /api/v1/legal-notice with an Accept header", async () => {
    const fetch = fetchReturning(jsonResponse(legalNoticeBody()));
    await createPublicApiClient({ fetch }).getLegalNotice();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/legal-notice", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("prefixes baseUrl", async () => {
    const fetch = fetchReturning(jsonResponse(legalNoticeBody()));
    await createPublicApiClient({ fetch, baseUrl: "https://api.test/" }).getLegalNotice();
    expect(fetch.mock.calls[0]?.[0]).toBe("https://api.test/api/v1/legal-notice");
  });

  test("maps the body to camelCase and ignores unknown keys", async () => {
    const body = legalNoticeBody({ extra: 1 });
    (body["holders"] as Record<string, unknown>[])[0]!["extra"] = true;
    const notice = await createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) }).getLegalNotice();
    expect(notice).toEqual({
      holders: [
        { name: "Persona Uno", nif: "00000000T" },
        { name: "Persona Dos", nif: null },
      ],
      contactEmail: "contacto@ideologiapp.test",
      address: "Calle Ficticia 1",
    });
  });

  test("accepts the empty notice", async () => {
    const fetch = fetchReturning(jsonResponse({ holders: [], contact_email: null, address: null }));
    expect(await createPublicApiClient({ fetch }).getLegalNotice()).toEqual({
      holders: [],
      contactEmail: null,
      address: null,
    });
  });

  test.each<[string, Record<string, unknown>, string]>([
    ["a body that is an array", { __array: true }, "legal_notice must be an object"],
    ["missing holders", { holders: undefined }, "legal_notice.holders must be an array"],
    ["holders not an array", { holders: "Persona Uno" }, "legal_notice.holders must be an array"],
    ["a holder that is not an object", { holders: ["Persona Uno"] }, "holders[0] must be an object"],
    ["an empty name", { holders: [{ name: "", nif: null }] }, "holders[0].name must be a non-empty string"],
    ["a missing name", { holders: [{ nif: null }] }, "holders[0].name must be a non-empty string"],
    ["an empty nif", { holders: [{ name: "Persona Uno", nif: "" }] }, "holders[0].nif must be null or a non-empty string"],
    ["a missing nif", { holders: [{ name: "Persona Uno" }] }, "holders[0].nif must be null or a non-empty string"],
    ["an email without @", { contact_email: "contacto" }, 'legal_notice.contact_email must be null or an address with "@" and no spaces'],
    ["an email with a space", { contact_email: "a b@ideologiapp.test" }, 'legal_notice.contact_email must be null or an address with "@" and no spaces'],
    ["a missing email", { contact_email: undefined }, 'legal_notice.contact_email must be null or an address with "@" and no spaces'],
    ["an empty address", { address: "" }, "legal_notice.address must be null or a non-empty string"],
    ["a numeric address", { address: 1 }, "legal_notice.address must be null or a non-empty string"],
  ])("%s is an invalid response naming the field", async (_name, overrides, message) => {
    const body = "__array" in overrides ? [] : legalNoticeBody(overrides);
    const error = await rejection(
      createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) }).getLegalNotice(),
    );
    expect(error.kind).toBe("invalid_response");
    expect(error.message).toBe(`GET /api/v1/legal-notice: ${message}`);
  });

  test("a 500 is an http error and json() is not called", async () => {
    const response = jsonResponse({}, 500);
    const error = await rejection(
      createPublicApiClient({ fetch: fetchReturning(response) }).getLegalNotice(),
    );
    expect(error.kind).toBe("http");
    expect(error.status).toBe(500);
    expect(response.json).not.toHaveBeenCalled();
  });

  test("a rejected fetch is a network error", async () => {
    const fetch = vi.fn<FetchLike>(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = await rejection(createPublicApiClient({ fetch }).getLegalNotice());
    expect(error.kind).toBe("network");
  });

  test("a body that is not JSON is an invalid response", async () => {
    const response: HttpResponseLike = {
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token")),
    };
    const error = await rejection(createPublicApiClient({ fetch: fetchReturning(response) }).getLegalNotice());
    expect(error.kind).toBe("invalid_response");
  });
});

// donate-buymeacoffee: fictitious profile only.
const DONATION = "https://www.buymeacoffee.com/perfil_de_prueba";

describe("createPublicApiClient getDonationUrl", () => {
  test("sends exactly one bare GET to /api/v1/donation with an Accept header", async () => {
    const fetch = fetchReturning(jsonResponse({ url: DONATION }));
    await createPublicApiClient({ fetch }).getDonationUrl();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/donation", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  test("prefixes baseUrl", async () => {
    const fetch = fetchReturning(jsonResponse({ url: null }));
    await createPublicApiClient({ fetch, baseUrl: "https://api.test/" }).getDonationUrl();
    expect(fetch.mock.calls[0]?.[0]).toBe("https://api.test/api/v1/donation");
  });

  test.each([DONATION, "https://buymeacoffee.com/perfil_de_prueba"])(
    "returns the configured URL %s unchanged",
    async (url) => {
      const fetch = fetchReturning(jsonResponse({ url, extra: 1 }));
      expect(await createPublicApiClient({ fetch }).getDonationUrl()).toBe(url);
    },
  );

  test("returns null when not configured", async () => {
    const fetch = fetchReturning(jsonResponse({ url: null }));
    expect(await createPublicApiClient({ fetch }).getDonationUrl()).toBeNull();
  });

  test.each<[string, unknown, string]>([
    ["a body that is an array", [], "donation must be an object"],
    ["a body that is null", null, "donation must be an object"],
    ["a missing url", {}, "donation.url must be null or"],
    ["a numeric url", { url: 1 }, "donation.url must be null or"],
    ["an empty url", { url: "" }, "donation.url must be null or"],
    ["an http url", { url: "http://www.buymeacoffee.com/perfil_de_prueba" }, "donation.url must be null or"],
    ["a url with a query", { url: `${DONATION}?ref=x` }, "donation.url must be null or"],
    ["another host", { url: "https://buymeacoffee.com.evil.test/perfil" }, "donation.url must be null or"],
    ["a javascript url", { url: "javascript:alert(1)" }, "donation.url must be null or"],
  ])("%s is an invalid response naming donation.url", async (_name, body, message) => {
    const error = await rejection(
      createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) }).getDonationUrl(),
    );
    expect(error.kind).toBe("invalid_response");
    expect(error.message.startsWith(`GET /api/v1/donation: ${message}`)).toBe(true);
  });

  test("a 500 is an http error and json() is not called", async () => {
    const response = jsonResponse({}, 500);
    const error = await rejection(
      createPublicApiClient({ fetch: fetchReturning(response) }).getDonationUrl(),
    );
    expect(error.kind).toBe("http");
    expect(error.status).toBe(500);
    expect(response.json).not.toHaveBeenCalled();
  });

  test("a rejected fetch is a network error", async () => {
    const fetch = vi.fn<FetchLike>(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = await rejection(createPublicApiClient({ fetch }).getDonationUrl());
    expect(error.kind).toBe("network");
  });

  test("a body that is not JSON is an invalid response", async () => {
    const response: HttpResponseLike = {
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token")),
    };
    const error = await rejection(createPublicApiClient({ fetch: fetchReturning(response) }).getDonationUrl());
    expect(error.kind).toBe("invalid_response");
  });
});

// --- public-dataset-api-v2 ------------------------------------------------------------

describe("createPublicApiClient Election generation", () => {
  test("parses legacy, v2 and null", async () => {
    const fetch = fetchReturning(
      jsonResponse({
        elections: [
          electionBody({ id: 3, published_dataset_version_id: 9, published_dataset_version_generation: "v2" }),
          electionBody({ id: 2, published_dataset_version_id: 5, published_dataset_version_generation: "legacy" }),
          electionBody({ id: 1, published_dataset_version_id: null, published_dataset_version_generation: null }),
        ],
      }),
    );
    const elections = await createPublicApiClient({ fetch }).listElections();
    expect(elections.map((e) => e.publishedDatasetVersionGeneration)).toEqual(["v2", "legacy", null]);
  });

  test("a body without the key reads legacy when an id is set and null otherwise", async () => {
    const fetch = fetchReturning(
      jsonResponse({
        elections: [electionBody(), electionBody({ id: 2, published_dataset_version_id: null })],
      }),
    );
    const elections = await createPublicApiClient({ fetch }).listElections();
    expect(elections.map((e) => e.publishedDatasetVersionGeneration)).toEqual(["legacy", null]);
  });

  test.each([
    [{ published_dataset_version_generation: "v3" }, "must be one of legacy, v2"],
    [{ published_dataset_version_generation: null }, "must be one of legacy, v2"],
    [
      { published_dataset_version_id: null, published_dataset_version_generation: "v2" },
      "must be null when there is no published version",
    ],
  ])("rejects an inconsistent generation %#", async (overrides, message) => {
    const fetch = fetchReturning(jsonResponse(electionBody(overrides)));
    const error = await rejection(createPublicApiClient({ fetch }).getElection(1));
    expect(error.kind).toBe("invalid_response");
    expect(error.message).toContain(`election.published_dataset_version_generation ${message}`);
  });
});

function summaryBody(code: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    code,
    name: `Provincia ${code}`,
    available: false,
    unavailable_reason: "fewer_than_two_parties",
    valid_statement_count: 0,
    offered_lengths: [],
    ...overrides,
  };
}

function listBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 10,
    election_id: 1,
    created_at: "2026-11-25T10:30:00Z",
    constituencies: [
      summaryBody("01", { unavailable_reason: "too_few_statements", valid_statement_count: 1 }),
      summaryBody("28", {
        available: true,
        unavailable_reason: null,
        valid_statement_count: 24,
        offered_lengths: [20, 24],
      }),
    ],
    ...overrides,
  };
}

function proposalBody(id: number, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { id, text: `Propuesta ${id}.`, page: id, url: null, source_document_id: 3, ...overrides };
}

function questionnaireBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    dataset_version_id: 10,
    code: "28",
    name: "Madrid",
    available: true,
    unavailable_reason: null,
    offered_lengths: [2],
    statements: [
      { id: 101, rank: 1, text: "Primera.", topic: "housing", context_note: "Nota." },
      { id: 104, rank: 2, text: "Segunda.", topic: "economy", context_note: null },
    ],
    parties: [
      {
        id: 1,
        name: "Partido Alfa",
        short_name: "PA",
        logo_url: "/api/v1/parties/1/logo?v=0123456789abcdef",
        positions: [
          { statement_id: 101, value: 2, evidence_proposal_ids: [1, 6] },
          { statement_id: 104, value: 0, evidence_proposal_ids: [3] },
        ],
        evidence: [
          proposalBody(1, { url: "https://alfa.example/p.pdf" }),
          proposalBody(3),
          proposalBody(6),
        ],
      },
      {
        id: 2,
        name: "Bloque Beta",
        short_name: "BB",
        logo_url: null,
        positions: [
          { statement_id: 101, value: "no_stance", evidence_proposal_ids: [] },
          { statement_id: 104, value: -1, evidence_proposal_ids: [5] },
        ],
        evidence: [proposalBody(5)],
      },
    ],
    excluded_parties: [{ id: 4, name: "Xarxa", short_name: "XI", reason: "no_manifesto" }],
    ...overrides,
  };
}

function proposalsBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    dataset_version_id: 10,
    code: "28",
    category: "housing",
    parties: [
      { party_id: 1, proposals: [proposalBody(1), proposalBody(2)] },
      { party_id: 2, proposals: [] },
    ],
    ...overrides,
  };
}

describe("createPublicApiClient listConstituencies", () => {
  test("requests the exact path and maps to camelCase", async () => {
    const fetch = fetchReturning(jsonResponse(listBody()));
    const list = await createPublicApiClient({ fetch }).listConstituencies(10);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/dataset-versions/10/constituencies", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    expect(list).toEqual({
      id: 10,
      electionId: 1,
      createdAt: "2026-11-25T10:30:00Z",
      constituencies: [
        {
          code: "01",
          name: "Provincia 01",
          available: false,
          unavailableReason: "too_few_statements",
          validStatementCount: 1,
          offeredLengths: [],
        },
        {
          code: "28",
          name: "Provincia 28",
          available: true,
          unavailableReason: null,
          validStatementCount: 24,
          offeredLengths: [20, 24],
        },
      ],
    });
  });

  test.each([
    [{ constituencies: [summaryBody("1")] }, "constituencies[0].code must be two digits"],
    [{ constituencies: [summaryBody("28", { unavailable_reason: "nope" })] }, "unavailable_reason must be one of"],
    [{ constituencies: [summaryBody("28", { available: true })] }, "unavailable_reason must be null when available"],
    [{ constituencies: [summaryBody("28", { offered_lengths: [20] })] }, "must be empty when unavailable"],
    [
      {
        constituencies: [
          summaryBody("28", { available: true, unavailable_reason: null, valid_statement_count: 3, offered_lengths: [] }),
        ],
      },
      "must be non-empty when available",
    ],
    [
      {
        constituencies: [
          summaryBody("28", { available: true, unavailable_reason: null, valid_statement_count: 3, offered_lengths: [3, 3] }),
        ],
      },
      "strictly increasing",
    ],
    [
      {
        constituencies: [
          summaryBody("28", { available: true, unavailable_reason: null, valid_statement_count: 3, offered_lengths: [4] }),
        ],
      },
      "must not exceed valid_statement_count",
    ],
    [{ constituencies: [summaryBody("28"), summaryBody("01")] }, "constituencies[1].code must follow"],
    [{ created_at: "2026-11-25" }, "created_at must be"],
  ])("rejects a contract violation %#", async (overrides, message) => {
    const fetch = fetchReturning(jsonResponse(listBody(overrides)));
    const error = await rejection(createPublicApiClient({ fetch }).listConstituencies(10));
    expect(error.kind).toBe("invalid_response");
    expect(error.message).toContain(message);
    expect(error.message).toContain("GET /api/v1/dataset-versions/10/constituencies:");
  });

  test("a bad version id throws before any request", async () => {
    const fetch = fetchReturning(jsonResponse(listBody()));
    const api = createPublicApiClient({ fetch });
    for (const id of [0, -1, 1.5, Number.NaN]) {
      await expect(api.listConstituencies(id)).rejects.toBeInstanceOf(RangeError);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  test("a 404 (e.g. dataset_version_is_legacy) is an http error", async () => {
    const response = jsonResponse({ error: { code: "dataset_version_is_legacy", message: "x" } }, 404);
    const error = await rejection(
      createPublicApiClient({ fetch: fetchReturning(response) }).listConstituencies(5),
    );
    expect(error.kind).toBe("http");
    expect(error.status).toBe(404);
  });
});

describe("createPublicApiClient getConstituencyQuestionnaire", () => {
  test("requests the exact path, maps to camelCase and resolves Evidence ids", async () => {
    const fetch = fetchReturning(jsonResponse(questionnaireBody()));
    const result = await createPublicApiClient({ fetch }).getConstituencyQuestionnaire(10, "28");
    expect(fetch).toHaveBeenCalledWith("/api/v1/dataset-versions/10/constituencies/28", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    const one = { id: 1, text: "Propuesta 1.", page: 1, url: "https://alfa.example/p.pdf", sourceDocumentId: 3 };
    const three = { id: 3, text: "Propuesta 3.", page: 3, url: null, sourceDocumentId: 3 };
    const five = { id: 5, text: "Propuesta 5.", page: 5, url: null, sourceDocumentId: 3 };
    const six = { id: 6, text: "Propuesta 6.", page: 6, url: null, sourceDocumentId: 3 };
    expect(result).toEqual({
      datasetVersionId: 10,
      code: "28",
      name: "Madrid",
      available: true,
      unavailableReason: null,
      offeredLengths: [2],
      statements: [
        { id: 101, rank: 1, text: "Primera.", topic: "housing", contextNote: "Nota." },
        { id: 104, rank: 2, text: "Segunda.", topic: "economy", contextNote: null },
      ],
      parties: [
        {
          id: 1,
          name: "Partido Alfa",
          shortName: "PA",
          logoUrl: "/api/v1/parties/1/logo?v=0123456789abcdef",
          positions: [
            { statementId: 101, value: 2, evidence: [one, six] },
            { statementId: 104, value: 0, evidence: [three] },
          ],
        },
        {
          id: 2,
          name: "Bloque Beta",
          shortName: "BB",
          logoUrl: null,
          positions: [
            { statementId: 101, value: "no_stance", evidence: [] },
            { statementId: 104, value: -1, evidence: [five] },
          ],
        },
      ],
      excludedParties: [{ id: 4, name: "Xarxa", shortName: "XI", reason: "no_manifesto" }],
    });
  });

  test("parses an unavailable Constituency", async () => {
    const body = questionnaireBody({
      code: "01",
      available: false,
      unavailable_reason: "low_party_coverage",
      offered_lengths: [],
      statements: [],
      parties: [{ id: 1, name: "A", short_name: "A", logo_url: null, positions: [], evidence: [] }],
      excluded_parties: [],
    });
    const result = await createPublicApiClient({ fetch: fetchReturning(jsonResponse(body)) })
      .getConstituencyQuestionnaire(10, "01");
    expect(result.available).toBe(false);
    expect(result.unavailableReason).toBe("low_party_coverage");
    expect(result.parties[0]?.positions).toEqual([]);
  });

  function withParty(index: number, party: Record<string, unknown>): Record<string, unknown> {
    const body = questionnaireBody();
    const parties = [...(body["parties"] as Record<string, unknown>[])];
    parties[index] = { ...parties[index], ...party };
    return { parties };
  }

  const alfaPositions = (positions: unknown[]) => withParty(0, { positions });

  test.each([
    [
      alfaPositions([
        { statement_id: 104, value: 0, evidence_proposal_ids: [3] },
        { statement_id: 101, value: 2, evidence_proposal_ids: [1] },
      ]),
      "parties[0].positions[0].statement_id must be 101 (Statement order)",
    ],
    [alfaPositions([{ statement_id: 101, value: 2, evidence_proposal_ids: [1] }]), "one entry per Statement (2), got 1"],
    [
      alfaPositions([
        { statement_id: 101, value: 2, evidence_proposal_ids: [99] },
        { statement_id: 104, value: 0, evidence_proposal_ids: [3] },
      ]),
      "evidence_proposal_ids[0] must be the id of an entry of the party's evidence",
    ],
    [
      alfaPositions([
        { statement_id: 101, value: "no_stance", evidence_proposal_ids: [1] },
        { statement_id: 104, value: 0, evidence_proposal_ids: [3] },
      ]),
      'must be empty when value is "no_stance"',
    ],
    [
      alfaPositions([
        { statement_id: 101, value: 2, evidence_proposal_ids: [] },
        { statement_id: 104, value: 0, evidence_proposal_ids: [3] },
      ]),
      'must not be empty when value is not "no_stance"',
    ],
    [
      alfaPositions([
        { statement_id: 101, value: 3, evidence_proposal_ids: [1] },
        { statement_id: 104, value: 0, evidence_proposal_ids: [3] },
      ]),
      "value must be an integer from -2 to 2",
    ],
    [withParty(0, { evidence: [proposalBody(1), proposalBody(1)] }), "evidence[1].id 1 is a duplicate"],
    [
      {
        statements: [
          { id: 101, rank: 1, text: "A.", topic: "housing", context_note: null },
          { id: 101, rank: 2, text: "B.", topic: "housing", context_note: null },
        ],
      },
      "statements[1].id 101 is a duplicate",
    ],
    [
      {
        statements: [
          { id: 101, rank: 2, text: "A.", topic: "housing", context_note: null },
          { id: 104, rank: 1, text: "B.", topic: "economy", context_note: null },
        ],
      },
      "statements[0].rank must be 1",
    ],
    [
      {
        statements: [
          { id: 101, rank: 1, text: "A.", topic: "housing", context_note: null },
          { id: 104, rank: 1, text: "B.", topic: "economy", context_note: null },
        ],
      },
      "statements[1].rank must be 2",
    ],
    [{ code: "31" }, "constituency.code must be 28"],
    [{ code: "2" }, "constituency.code must be two digits"],
    [{ dataset_version_id: 11 }, "constituency.dataset_version_id must be 10"],
    [{ unavailable_reason: "too_few_statements" }, "unavailable_reason must be null when available"],
    [{ available: false, unavailable_reason: "nope", offered_lengths: [] }, "unavailable_reason must be one of"],
    [{ available: false, unavailable_reason: "too_few_statements", offered_lengths: [] }, "statements must be empty when unavailable"],
    [{ offered_lengths: [3] }, "offered_lengths must not exceed the number of statements"],
    [
      { excluded_parties: [{ id: 4, name: "X", short_name: "X", reason: "banned" }] },
      "excluded_parties[0].reason must be one of no_manifesto, discarded_at_review, too_few_proposals",
    ],
    [
      { excluded_parties: [{ id: 2, name: "X", short_name: "X", reason: "no_manifesto" }] },
      "excluded_parties[0].id 2 is also a running party",
    ],
    [withParty(1, { id: 1 }), "parties[1] must follow the previous party by id"],
  ])("rejects a contract violation %#", async (overrides, message) => {
    const fetch = fetchReturning(jsonResponse(questionnaireBody(overrides)));
    const error = await rejection(createPublicApiClient({ fetch }).getConstituencyQuestionnaire(10, "28"));
    expect(error.kind).toBe("invalid_response");
    expect(error.message).toContain(message);
  });

  test("a bad code throws before any request", async () => {
    const fetch = fetchReturning(jsonResponse(questionnaireBody()));
    const api = createPublicApiClient({ fetch });
    for (const code of ["1", "abc", "281", " 28", "2a", ""]) {
      await expect(api.getConstituencyQuestionnaire(10, code)).rejects.toBeInstanceOf(RangeError);
    }
    await expect(api.getConstituencyQuestionnaire(0, "28")).rejects.toBeInstanceOf(RangeError);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("createPublicApiClient getConstituencyProposals", () => {
  test("requests the exact path and maps to camelCase", async () => {
    const fetch = fetchReturning(jsonResponse(proposalsBody()));
    const result = await createPublicApiClient({ fetch }).getConstituencyProposals(10, "28", "housing");
    expect(fetch).toHaveBeenCalledWith("/api/v1/dataset-versions/10/constituencies/28/proposals/housing", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    expect(result).toEqual({
      datasetVersionId: 10,
      code: "28",
      category: "housing",
      parties: [
        {
          partyId: 1,
          proposals: [
            { id: 1, text: "Propuesta 1.", page: 1, url: null, sourceDocumentId: 3 },
            { id: 2, text: "Propuesta 2.", page: 2, url: null, sourceDocumentId: 3 },
          ],
        },
        { partyId: 2, proposals: [] },
      ],
    });
  });

  test.each([
    [{ category: "economy" }, "constituency_proposals.category must be housing"],
    [{ code: "31" }, "constituency_proposals.code must be 28"],
    [{ dataset_version_id: 9 }, "constituency_proposals.dataset_version_id must be 10"],
    [{ parties: [{ party_id: 2, proposals: [] }, { party_id: 1, proposals: [] }] }, "parties[1] must follow"],
    [{ parties: [{ party_id: 1, proposals: [proposalBody(1), proposalBody(1)] }] }, "proposals[1].id is a duplicate"],
    [{ parties: [{ party_id: 1, proposals: [proposalBody(1, { page: 0 })] }] }, "page must be a positive integer"],
  ])("rejects a contract violation %#", async (overrides, message) => {
    const fetch = fetchReturning(jsonResponse(proposalsBody(overrides)));
    const error = await rejection(createPublicApiClient({ fetch }).getConstituencyProposals(10, "28", "housing"));
    expect(error.kind).toBe("invalid_response");
    expect(error.message).toContain(message);
  });

  test("a bad code or category throws before any request", async () => {
    const fetch = fetchReturning(jsonResponse(proposalsBody()));
    const api = createPublicApiClient({ fetch });
    await expect(api.getConstituencyProposals(10, "1", "housing")).rejects.toBeInstanceOf(RangeError);
    for (const category of ["Housing", "nope", "", "housing/../x"]) {
      await expect(
        api.getConstituencyProposals(10, "28", category as "housing"),
      ).rejects.toBeInstanceOf(RangeError);
    }
    expect(fetch).not.toHaveBeenCalled();
  });
});
