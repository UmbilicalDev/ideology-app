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
