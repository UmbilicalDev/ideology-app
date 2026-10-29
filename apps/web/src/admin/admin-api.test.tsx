// feedback-admin Decision 14: the admin API client (mocked fetch only).
import { describe, expect, test } from "vitest";

import { AdminApiError, createAdminApiClient, type AdminFetchLike } from "./admin-api";
import { fakeAdminServer, message, response } from "./fake-admin-server";

async function rejection(promise: Promise<unknown>): Promise<AdminApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(AdminApiError);
    return error as AdminApiError;
  }
  throw new Error("expected a rejection");
}

describe("createAdminApiClient", () => {
  test("sign-in keeps the CSRF token in memory and sends it on state changes only", async () => {
    const server = fakeAdminServer({ messages: [message(1)] });
    const api = createAdminApiClient({ fetch: server.fetch });
    expect(await api.signIn("prueba", "contraseña-de-prueba")).toEqual({ username: "prueba" });
    const [signIn] = server.state.calls;
    expect(signIn).toMatchObject({ method: "POST", url: "/admin/api/v1/session" });
    expect(signIn!.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(signIn!.body!)).toEqual({ username: "prueba", password: "contraseña-de-prueba" });

    await api.listFeedback({ reviewed: "all" });
    await api.markReviewed(1);
    await api.unmarkReviewed(1);
    await api.deleteFeedback(1);
    await api.signOut();
    const [, list, mark, unmark, remove, out] = server.state.calls;
    expect(list!.headers["X-CSRF-Token"]).toBeUndefined();
    for (const call of [mark, unmark, remove, out]) {
      expect(call!.headers["X-CSRF-Token"]).toBe("csrf-1");
    }
    expect([mark, unmark, remove, out].map((c) => `${c!.method} ${c!.url}`)).toEqual([
      "POST /admin/api/v1/feedback/1/review",
      "DELETE /admin/api/v1/feedback/1/review",
      "DELETE /admin/api/v1/feedback/1",
      "DELETE /admin/api/v1/session",
    ]);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  test("getSession restores the CSRF token after a reload", async () => {
    const server = fakeAdminServer({ signedIn: true, messages: [message(3)] });
    const api = createAdminApiClient({ fetch: server.fetch, baseUrl: "http://127.0.0.1:8010" });
    expect(await api.getSession()).toEqual({ username: "prueba" });
    await api.markReviewed(3);
    const mark = server.state.calls[1]!;
    expect(mark.url).toBe("http://127.0.0.1:8010/admin/api/v1/feedback/3/review");
    expect(mark.headers["X-CSRF-Token"]).toBe("csrf-1");
  });

  test("listFeedback builds the query and parses the page", async () => {
    const server = fakeAdminServer({
      signedIn: true,
      messages: [message(1), message(2, { reviewed_at: "2026-10-29T15:00:00Z" })],
    });
    const api = createAdminApiClient({ fetch: server.fetch });
    const page = await api.listFeedback({ from: "2026-10-01", to: "2026-10-31", reviewed: "yes" }, 9);
    expect(server.state.calls[0]!.url).toBe(
      "/admin/api/v1/feedback?from=2026-10-01&to=2026-10-31&reviewed=yes&before_id=9",
    );
    expect(page).toEqual({
      messages: [
        {
          id: 2,
          message: "Mensaje 2",
          origin: "results",
          createdAt: "2026-10-02T14:05:00Z",
          reviewedAt: "2026-10-29T15:00:00Z",
        },
      ],
      nextBeforeId: null,
    });
    await api.listFeedback({ from: "", reviewed: "all" });
    expect(server.state.calls[1]!.url).toBe("/admin/api/v1/feedback?reviewed=all");
  });

  test.each([
    [response(401, { error: { code: "not_signed_in", message: "" } }), "not_signed_in", 401],
    [response(401, { error: { code: "admin_not_configured", message: "" } }), "not_configured", 401],
    [response(503, { error: { code: "admin_not_configured", message: "" } }), "not_configured", 503],
    [response(401, { error: { code: "invalid_credentials", message: "" } }), "invalid_credentials", 401],
    [response(403, { error: { code: "csrf_failed", message: "" } }), "csrf", 403],
    [response(404, { error: { code: "feedback_not_found", message: "" } }), "not_found", 404],
    [response(500), "http", 500],
    [response(200, { username: "prueba" }), "http", 200],
    [response(200, "not json object"), "http", 200],
  ] as const)("maps %# to %s", async (reply, kind, status) => {
    const api = createAdminApiClient({ fetch: async () => reply });
    const error = await rejection(api.signIn("prueba", "x"));
    expect(error.kind).toBe(kind);
    expect(error.status).toBe(status);
  });

  test("rate limited carries Retry-After", async () => {
    const api = createAdminApiClient({
      fetch: async () =>
        response(429, { error: { code: "rate_limited", message: "" } }, { "Retry-After": "600" }),
    });
    const error = await rejection(api.signIn("prueba", "x"));
    expect(error.kind).toBe("rate_limited");
    expect(error.retryAfterSeconds).toBe(600);
  });

  test("a network failure is kind network", async () => {
    const failing: AdminFetchLike = async () => {
      throw new TypeError("Failed to fetch");
    };
    const error = await rejection(createAdminApiClient({ fetch: failing }).getSession());
    expect(error.kind).toBe("network");
    expect(error.status).toBeUndefined();
  });

  test.each([
    { id: 0, message: "x", origin: "landing", created_at: "2026-10-29T14:05:00Z", reviewed_at: null },
    { id: 1, message: 2, origin: "landing", created_at: "2026-10-29T14:05:00Z", reviewed_at: null },
    { id: 1, message: "x", origin: "admin", created_at: "2026-10-29T14:05:00Z", reviewed_at: null },
    { id: 1, message: "x", origin: "landing", created_at: "29/10/2026", reviewed_at: null },
    { id: 1, message: "x", origin: "landing", created_at: "2026-10-29T14:05:00Z", reviewed_at: 5 },
  ])("rejects a malformed message %#", async (bad) => {
    const api = createAdminApiClient({
      fetch: async () => response(200, { messages: [bad], next_before_id: null }),
    });
    expect((await rejection(api.listFeedback({ reviewed: "all" }))).kind).toBe("http");
  });

  test("a 401 forgets the CSRF token", async () => {
    const server = fakeAdminServer({ signedIn: true, messages: [message(1)] });
    const api = createAdminApiClient({ fetch: server.fetch });
    await api.getSession();
    server.state.signedIn = false;
    expect((await rejection(api.markReviewed(1))).kind).toBe("not_signed_in");
    server.state.signedIn = true;
    expect((await rejection(api.markReviewed(1))).kind).toBe("csrf");
    expect(server.state.calls[2]!.headers["X-CSRF-Token"]).toBeUndefined();
  });
});
