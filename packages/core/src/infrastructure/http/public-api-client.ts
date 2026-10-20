// HTTP adapter for the public API (`/api/v1`). It checks the response
// contract and maps snake_case keys to camelCase once. `packages/core` has no
// DOM types, so `fetch` and `Response` are described structurally here.
import type { PublicApi } from "../../application/public-api";
import type { Election, ElectionStatus } from "../../domain/election";

export interface HttpResponseLike {
  readonly ok: boolean;
  readonly status: number;
  json(): Promise<unknown>;
}

export type FetchLike = (
  url: string,
  init: { readonly method: "GET"; readonly headers: Readonly<Record<string, string>> },
) => Promise<HttpResponseLike>;

export type PublicApiErrorKind = "network" | "http" | "invalid_response";

export class PublicApiError extends Error {
  override readonly name = "PublicApiError";
  readonly kind: PublicApiErrorKind;
  readonly status: number | null;

  constructor(kind: PublicApiErrorKind, message: string, status: number | null = null) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

export interface PublicApiClientOptions {
  readonly fetch: FetchLike;
  /** Origin to prefix to `/api/v1/...`; default `""` (same origin). */
  readonly baseUrl?: string;
}

const ELECTION_STATUSES: readonly ElectionStatus[] = ["draft", "active", "archived"];
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

class ContractError extends Error {}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function requireString(item: Record<string, unknown>, key: string, path: string): string {
  const value = item[key];
  if (typeof value !== "string") {
    throw new ContractError(`${path}.${key} must be a string`);
  }
  return value;
}

function parseElection(value: unknown, path: string): Election {
  if (!isRecord(value)) {
    throw new ContractError(`${path} must be an object`);
  }
  const id = value["id"];
  if (!isPositiveSafeInteger(id)) {
    throw new ContractError(`${path}.id must be a positive integer`);
  }
  const country = requireString(value, "country", path);
  const type = requireString(value, "type", path);
  const name = requireString(value, "name", path);
  const date = value["date"];
  if (typeof date !== "string" || !DATE_PATTERN.test(date)) {
    throw new ContractError(`${path}.date must be YYYY-MM-DD`);
  }
  const status = value["status"];
  if (typeof status !== "string" || !(ELECTION_STATUSES as readonly string[]).includes(status)) {
    throw new ContractError(`${path}.status must be one of ${ELECTION_STATUSES.join(", ")}`);
  }
  const published = value["published_dataset_version_id"];
  if (published !== null && !isPositiveSafeInteger(published)) {
    throw new ContractError(
      `${path}.published_dataset_version_id must be null or a positive integer`,
    );
  }
  return {
    id,
    country,
    type,
    date,
    name,
    status: status as ElectionStatus,
    publishedDatasetVersionId: published,
  };
}

function parseElectionList(body: unknown): readonly Election[] {
  if (!isRecord(body)) {
    throw new ContractError("response body must be an object");
  }
  const elections = body["elections"];
  if (!Array.isArray(elections)) {
    throw new ContractError("elections must be an array");
  }
  return elections.map((item: unknown, index) => parseElection(item, `elections[${index}]`));
}

export function createPublicApiClient(options: PublicApiClientOptions): PublicApi {
  // Called as a plain function: `window.fetch` invoked as a method of another
  // object throws "Illegal invocation".
  const fetchFn = options.fetch;
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");

  async function getJson(path: string): Promise<unknown> {
    let response: HttpResponseLike;
    try {
      response = await fetchFn(`${baseUrl}${path}`, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
    } catch {
      throw new PublicApiError("network", `GET ${path} failed: network error`);
    }
    if (!response.ok) {
      throw new PublicApiError(
        "http",
        `GET ${path} failed: HTTP ${response.status}`,
        response.status,
      );
    }
    try {
      return await response.json();
    } catch {
      throw new PublicApiError("invalid_response", `GET ${path}: response body is not JSON`);
    }
  }

  return {
    async listElections() {
      const path = "/api/v1/elections";
      const body = await getJson(path);
      try {
        return parseElectionList(body);
      } catch (error) {
        if (error instanceof ContractError) {
          throw new PublicApiError("invalid_response", `GET ${path}: ${error.message}`);
        }
        throw error;
      }
    },
  };
}
