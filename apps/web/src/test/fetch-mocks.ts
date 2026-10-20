import type { HttpResponseLike } from "@ideology-app/core";

export function jsonResponse(body: unknown, status = 200): HttpResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  };
}

/** A non-JSON error response, like the server's `text/plain` 500. */
export function textResponse(status: number): HttpResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.reject(new SyntaxError("Unexpected token 'I'")),
  };
}

export function electionJson(overrides: Record<string, unknown> = {}): Record<string, unknown> {
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
