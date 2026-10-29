// Test helper: an in-memory stand-in for /admin/api/v1 behind an AdminFetchLike
// (never the network). Mirrors the server's status codes and JSON shapes.
import type { AdminFetchLike, AdminResponseLike } from "./admin-api";

export interface FakeMessage {
  id: number;
  message: string;
  origin: "landing" | "results";
  created_at: string;
  reviewed_at: string | null;
}

export interface FakeCall {
  readonly method: string;
  readonly url: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: string | undefined;
}

export interface FakeServerOptions {
  readonly configured?: boolean;
  readonly signedIn?: boolean;
  readonly messages?: FakeMessage[];
  readonly password?: string;
}

export function response(
  status: number,
  body?: unknown,
  headers: Record<string, string> = {},
): AdminResponseLike {
  const lower = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => lower[name.toLowerCase()] ?? null },
    json: async () => {
      if (body === undefined) throw new SyntaxError("no body");
      return body;
    },
  };
}

function error(status: number, code: string, headers: Record<string, string> = {}) {
  return response(status, { error: { code, message: code } }, headers);
}

export function message(id: number, overrides: Partial<FakeMessage> = {}): FakeMessage {
  const day = String(1 + ((id - 1) % 28)).padStart(2, "0");
  return {
    id,
    message: `Mensaje ${id}`,
    origin: id % 2 === 0 ? "results" : "landing",
    created_at: `2026-10-${day}T14:05:00Z`,
    reviewed_at: null,
    ...overrides,
  };
}

export function fakeAdminServer(options: FakeServerOptions = {}) {
  const state = {
    configured: options.configured ?? true,
    signedIn: options.signedIn ?? false,
    csrf: "csrf-1",
    messages: options.messages ?? [],
    password: options.password ?? "contraseña-de-prueba",
    calls: [] as FakeCall[],
    /** When set, the next request answers this instead. */
    next: null as null | (() => AdminResponseLike | Promise<AdminResponseLike>),
    /** Hold every request until release() (to observe pending states). */
    hold: false,
    held: [] as (() => void)[],
  };

  function release() {
    const waiting = state.held.splice(0);
    for (const resume of waiting) resume();
  }

  function needsSession(): AdminResponseLike | null {
    if (!state.configured) return error(401, "admin_not_configured");
    if (!state.signedIn) return error(401, "not_signed_in");
    return null;
  }

  function needsCsrf(headers: Readonly<Record<string, string>>): AdminResponseLike | null {
    return needsSession() ?? (headers["X-CSRF-Token"] === state.csrf ? null : error(403, "csrf_failed"));
  }

  function handle(method: string, url: string, headers: Readonly<Record<string, string>>, body?: string) {
    const parsed = new URL(url, "http://localhost");
    const path = parsed.pathname.replace(/^\/admin\/api\/v1/, "");
    if (path === "/session" && method === "POST") {
      if (!state.configured) return error(503, "admin_not_configured");
      const credentials = JSON.parse(body ?? "{}") as { username: string; password: string };
      if (credentials.username !== "prueba" || credentials.password !== state.password) {
        return error(401, "invalid_credentials");
      }
      state.signedIn = true;
      return response(200, { username: "prueba", csrf_token: state.csrf });
    }
    if (path === "/session" && method === "GET") {
      return needsSession() ?? response(200, { username: "prueba", csrf_token: state.csrf });
    }
    if (path === "/session" && method === "DELETE") {
      const refused = needsCsrf(headers);
      if (refused) return refused;
      state.signedIn = false;
      return response(204);
    }
    if (path === "/feedback" && method === "GET") {
      const refused = needsSession();
      if (refused) return refused;
      const from = parsed.searchParams.get("from");
      const to = parsed.searchParams.get("to");
      const reviewed = parsed.searchParams.get("reviewed") ?? "all";
      const beforeId = Number(parsed.searchParams.get("before_id") ?? Infinity);
      const limit = Number(parsed.searchParams.get("limit") ?? 50);
      const matching = [...state.messages]
        .sort((a, b) => b.id - a.id)
        .filter((m) => m.id < beforeId)
        .filter((m) => from === null || m.created_at.slice(0, 10) >= from)
        .filter((m) => to === null || m.created_at.slice(0, 10) <= to)
        .filter((m) => reviewed === "all" || (reviewed === "yes") === (m.reviewed_at !== null));
      const page = matching.slice(0, limit);
      return response(200, {
        messages: page.map((m) => ({ ...m })),
        next_before_id: matching.length > limit ? page[page.length - 1]!.id : null,
      });
    }
    const match = /^\/feedback\/(\d+)(\/review)?$/.exec(path);
    if (match) {
      const refused = needsCsrf(headers);
      if (refused) return refused;
      const id = Number(match[1]);
      const found = state.messages.find((m) => m.id === id);
      if (found === undefined) return error(404, "feedback_not_found");
      if (match[2] && method === "POST") {
        found.reviewed_at ??= "2026-10-29T15:00:00Z";
        return response(200, { ...found });
      }
      if (match[2] && method === "DELETE") {
        found.reviewed_at = null;
        return response(200, { ...found });
      }
      if (!match[2] && method === "DELETE") {
        state.messages = state.messages.filter((m) => m.id !== id);
        return response(204);
      }
    }
    return error(404, "not_found");
  }

  const fetch: AdminFetchLike = async (url, init) => {
    state.calls.push({ method: init.method, url, headers: init.headers, body: init.body });
    if (state.hold) {
      await new Promise<void>((resolve) => state.held.push(resolve));
    }
    const override = state.next;
    if (override !== null) {
      state.next = null;
      return override();
    }
    return handle(init.method, url, init.headers, init.body);
  };

  return { state, fetch, release };
}
