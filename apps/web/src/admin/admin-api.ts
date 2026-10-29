// The Operator admin API client (feedback-admin, Decision 14). It lives in
// apps/web, not packages/core: core is the Voter and mobile domain. Only
// src/admin/main.tsx passes the browser's fetch. The CSRF token is kept in
// memory only (never in storage); the session cookie is HttpOnly and is sent
// by the browser only to /admin/api.

export interface AdminResponseLike {
  readonly ok: boolean;
  readonly status: number;
  readonly headers: { get(name: string): string | null };
  json(): Promise<unknown>;
}

export type AdminFetchLike = (
  url: string,
  init: {
    readonly method: "GET" | "POST" | "DELETE";
    readonly headers: Readonly<Record<string, string>>;
    readonly body?: string;
  },
) => Promise<AdminResponseLike>;

export type AdminApiErrorKind =
  | "network"
  | "not_signed_in"
  | "not_configured"
  | "invalid_credentials"
  | "rate_limited"
  | "csrf"
  | "not_found"
  | "http";

export class AdminApiError extends Error {
  override readonly name = "AdminApiError";
  readonly kind: AdminApiErrorKind;
  readonly status: number | undefined;
  readonly retryAfterSeconds: number | undefined;

  constructor(kind: AdminApiErrorKind, status?: number, retryAfterSeconds?: number) {
    super(`admin API error: ${kind}${status === undefined ? "" : ` (${status})`}`);
    this.kind = kind;
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export type FeedbackOriginCode = "landing" | "results";
export type ReviewedFilter = "all" | "yes" | "no";

export interface AdminFeedbackMessage {
  readonly id: number;
  readonly message: string;
  readonly origin: FeedbackOriginCode;
  /** ISO 8601 UTC, `YYYY-MM-DDTHH:MM:SSZ`. */
  readonly createdAt: string;
  readonly reviewedAt: string | null;
}

export interface FeedbackFilters {
  /** Inclusive UTC days, `YYYY-MM-DD`; empty or absent means no bound. */
  readonly from?: string;
  readonly to?: string;
  readonly reviewed: ReviewedFilter;
}

export interface FeedbackPage {
  readonly messages: readonly AdminFeedbackMessage[];
  readonly nextBeforeId: number | null;
}

export interface AdminSessionInfo {
  readonly username: string;
}

export interface AdminApi {
  getSession(): Promise<AdminSessionInfo>;
  signIn(username: string, password: string): Promise<AdminSessionInfo>;
  signOut(): Promise<void>;
  listFeedback(filters: FeedbackFilters, beforeId?: number): Promise<FeedbackPage>;
  markReviewed(id: number): Promise<AdminFeedbackMessage>;
  unmarkReviewed(id: number): Promise<AdminFeedbackMessage>;
  deleteFeedback(id: number): Promise<void>;
}

export interface AdminApiClientOptions {
  readonly fetch: AdminFetchLike;
  /** Origin to prefix to `/admin/api/v1/...`; default `""` (same origin). */
  readonly baseUrl?: string;
}

const PREFIX = "/admin/api/v1";
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function invalid(status: number): AdminApiError {
  return new AdminApiError("http", status);
}

function parseSession(body: unknown, status: number): { username: string; csrfToken: string } {
  if (
    !isRecord(body) ||
    typeof body.username !== "string" ||
    body.username === "" ||
    typeof body.csrf_token !== "string" ||
    body.csrf_token === ""
  ) {
    throw invalid(status);
  }
  return { username: body.username, csrfToken: body.csrf_token };
}

function parseMessage(value: unknown, status: number): AdminFeedbackMessage {
  if (!isRecord(value)) {
    throw invalid(status);
  }
  const { id, message, origin, created_at: createdAt, reviewed_at: reviewedAt } = value;
  if (
    !isPositiveInteger(id) ||
    typeof message !== "string" ||
    (origin !== "landing" && origin !== "results") ||
    typeof createdAt !== "string" ||
    !TIMESTAMP.test(createdAt) ||
    !(reviewedAt === null || (typeof reviewedAt === "string" && TIMESTAMP.test(reviewedAt)))
  ) {
    throw invalid(status);
  }
  return { id, message, origin, createdAt, reviewedAt };
}

function parsePage(body: unknown, status: number): FeedbackPage {
  if (!isRecord(body) || !Array.isArray(body.messages)) {
    throw invalid(status);
  }
  const next = body.next_before_id;
  if (!(next === null || isPositiveInteger(next))) {
    throw invalid(status);
  }
  return { messages: body.messages.map((m) => parseMessage(m, status)), nextBeforeId: next };
}

async function errorCode(response: AdminResponseLike): Promise<string | undefined> {
  try {
    const body = await response.json();
    if (isRecord(body) && isRecord(body.error) && typeof body.error.code === "string") {
      return body.error.code;
    }
  } catch {
    // Not JSON: no code.
  }
  return undefined;
}

function retryAfter(response: AdminResponseLike): number | undefined {
  const raw = response.headers.get("Retry-After");
  if (raw === null || !/^\d+$/.test(raw.trim())) {
    return undefined;
  }
  return Number(raw.trim());
}

async function toError(response: AdminResponseLike): Promise<AdminApiError> {
  const status = response.status;
  const code = await errorCode(response);
  if (code === "admin_not_configured") {
    return new AdminApiError("not_configured", status);
  }
  switch (status) {
    case 401:
      return new AdminApiError(
        code === "invalid_credentials" ? "invalid_credentials" : "not_signed_in",
        status,
      );
    case 403:
      return new AdminApiError("csrf", status);
    case 404:
      return new AdminApiError("not_found", status);
    case 429:
      return new AdminApiError("rate_limited", status, retryAfter(response));
    default:
      return new AdminApiError("http", status);
  }
}

export function createAdminApiClient(options: AdminApiClientOptions): AdminApi {
  const fetchFn = options.fetch;
  const baseUrl = options.baseUrl ?? "";
  let csrfToken: string | null = null;

  async function request(
    method: "GET" | "POST" | "DELETE",
    path: string,
    body?: unknown,
  ): Promise<AdminResponseLike> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (method !== "GET" && csrfToken !== null) {
      headers["X-CSRF-Token"] = csrfToken;
    }
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    let response: AdminResponseLike;
    try {
      response = await fetchFn(`${baseUrl}${PREFIX}${path}`, {
        method,
        headers,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new AdminApiError("network");
    }
    if (!response.ok) {
      const error = await toError(response);
      if (error.kind === "not_signed_in" || error.kind === "not_configured") {
        csrfToken = null;
      }
      throw error;
    }
    return response;
  }

  async function json(response: AdminResponseLike): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      throw invalid(response.status);
    }
  }

  async function sessionFrom(response: AdminResponseLike): Promise<AdminSessionInfo> {
    const session = parseSession(await json(response), response.status);
    csrfToken = session.csrfToken;
    return { username: session.username };
  }

  function expectNoContent(response: AdminResponseLike): void {
    if (response.status !== 204) {
      throw invalid(response.status);
    }
  }

  return {
    async getSession() {
      return sessionFrom(await request("GET", "/session"));
    },
    async signIn(username, password) {
      return sessionFrom(await request("POST", "/session", { username, password }));
    },
    async signOut() {
      try {
        expectNoContent(await request("DELETE", "/session"));
      } finally {
        csrfToken = null;
      }
    },
    async listFeedback(filters, beforeId) {
      const params = new URLSearchParams();
      if (filters.from !== undefined && DAY.test(filters.from)) {
        params.set("from", filters.from);
      }
      if (filters.to !== undefined && DAY.test(filters.to)) {
        params.set("to", filters.to);
      }
      params.set("reviewed", filters.reviewed);
      if (beforeId !== undefined) {
        params.set("before_id", String(beforeId));
      }
      const response = await request("GET", `/feedback?${params.toString()}`);
      return parsePage(await json(response), response.status);
    },
    async markReviewed(id) {
      const response = await request("POST", `/feedback/${id}/review`);
      return parseMessage(await json(response), response.status);
    },
    async unmarkReviewed(id) {
      const response = await request("DELETE", `/feedback/${id}/review`);
      return parseMessage(await json(response), response.status);
    },
    async deleteFeedback(id) {
      expectNoContent(await request("DELETE", `/feedback/${id}`));
    },
  };
}
