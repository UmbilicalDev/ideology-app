// HTTP adapter for the public API (`/api/v1`). It checks the response
// contract and maps snake_case keys to camelCase once. `packages/core` has no
// DOM types, so `fetch` and `Response` are described structurally here.
import type { FeedbackApi, FeedbackInput } from "../../application/feedback-api";
import type { PublicApi } from "../../application/public-api";
import type {
  DatasetVersion,
  Evidence,
  Party,
  PartyPosition,
  Statement,
} from "../../domain/dataset-version";
import type { Election, ElectionStatus } from "../../domain/election";
import { DONATION_URL_FORMAT, isDonationUrl } from "../../domain/donation";
import type { LegalHolder, LegalNotice } from "../../domain/legal-notice";
import { NO_STANCE, type ScaleValue } from "../../domain/match-score";

export interface HttpResponseLike {
  readonly ok: boolean;
  readonly status: number;
  json(): Promise<unknown>;
}

export type FetchLike = (
  url: string,
  init: {
    readonly method: "GET" | "POST";
    readonly headers: Readonly<Record<string, string>>;
    readonly body?: string;
  },
) => Promise<HttpResponseLike>;

/** The read-only public API plus the single write, `sendFeedback`. */
export type PublicApiClient = PublicApi & FeedbackApi;

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
const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
// Same-origin only: the client never loads an image from another origin.
const LOGO_URL_PATTERN = /^\/api\/v1\/parties\/[1-9][0-9]*\/logo\?v=[0-9a-f]{16}$/;

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

function requirePositiveInteger(item: Record<string, unknown>, key: string, path: string): number {
  const value = item[key];
  if (!isPositiveSafeInteger(value)) {
    throw new ContractError(`${path}.${key} must be a positive integer`);
  }
  return value;
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new ContractError(`${path} must be an object`);
  }
  return value;
}

function requireArray(item: Record<string, unknown>, key: string, path: string): readonly unknown[] {
  const value = item[key];
  if (!Array.isArray(value)) {
    throw new ContractError(`${path}.${key} must be an array`);
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

function parseStatements(body: Record<string, unknown>): readonly Statement[] {
  const ids = new Set<number>();
  let previousPosition = 0;
  return requireArray(body, "statements", "dataset_version").map((value, index) => {
    const path = `statements[${index}]`;
    const item = requireRecord(value, path);
    const id = requirePositiveInteger(item, "id", path);
    if (ids.has(id)) {
      throw new ContractError(`${path}.id ${id} is a duplicate`);
    }
    ids.add(id);
    const position = requirePositiveInteger(item, "position", path);
    if (position <= previousPosition) {
      throw new ContractError(`${path}.position must be greater than the previous position`);
    }
    previousPosition = position;
    const text = requireString(item, "text", path);
    const topic = requireString(item, "topic", path);
    const contextNote = parseContextNote(item["context_note"], path);
    return { id, position, text, topic, contextNote };
  });
}

// A body cached before `context_note` existed has no key: read it as `null`.
function parseContextNote(value: unknown, path: string): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "string" || value === "") {
    throw new ContractError(`${path}.context_note must be null or a non-empty string`);
  }
  return value;
}

function isScaleValue(value: unknown): value is ScaleValue {
  return Number.isInteger(value) && (value as number) >= -2 && (value as number) <= 2;
}

function parseEvidence(value: unknown, path: string): Evidence {
  const item = requireRecord(value, path);
  const quote = requireString(item, "quote", path);
  const page = requirePositiveInteger(item, "page", path);
  const url = item["url"];
  if (url !== null && typeof url !== "string") {
    throw new ContractError(`${path}.url must be null or a string`);
  }
  const sourceDocumentId = requirePositiveInteger(item, "source_document_id", path);
  return { quote, page, url, sourceDocumentId };
}

function parsePosition(value: unknown, path: string, statementId: number): PartyPosition {
  const item = requireRecord(value, path);
  if (item["statement_id"] !== statementId) {
    throw new ContractError(`${path}.statement_id must be ${statementId} (Statement order)`);
  }
  const raw = item["value"];
  if (raw !== NO_STANCE && !isScaleValue(raw)) {
    throw new ContractError(`${path}.value must be an integer from -2 to 2 or "${NO_STANCE}"`);
  }
  const evidence = item["evidence"];
  if (raw === NO_STANCE) {
    if (evidence !== null) {
      throw new ContractError(`${path}.evidence must be null when value is "${NO_STANCE}"`);
    }
    return { statementId, value: raw, evidence: null };
  }
  if (evidence === null) {
    throw new ContractError(`${path}.evidence must not be null when value is not "${NO_STANCE}"`);
  }
  return { statementId, value: raw, evidence: parseEvidence(evidence, `${path}.evidence`) };
}

function parseParty(value: unknown, path: string, statements: readonly Statement[]): Party {
  const item = requireRecord(value, path);
  const id = requirePositiveInteger(item, "id", path);
  const name = requireString(item, "name", path);
  const shortName = requireString(item, "short_name", path);
  const logoUrl = parseLogoUrl(item["logo_url"], path);
  const rawPositions = requireArray(item, "positions", path);
  if (rawPositions.length !== statements.length) {
    throw new ContractError(
      `${path}.positions must have one entry per Statement (${statements.length}), got ${rawPositions.length}`,
    );
  }
  const positions = rawPositions.map((position, index) =>
    // The length check above guarantees statements[index] exists.
    parsePosition(position, `${path}.positions[${index}]`, (statements[index] as Statement).id),
  );
  return { id, name, shortName, logoUrl, positions };
}

// A body cached before `logo_url` existed has no key: read it as `null`.
function parseLogoUrl(value: unknown, path: string): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "string" || !LOGO_URL_PATTERN.test(value)) {
    throw new ContractError(
      `${path}.logo_url must be null or a path like /api/v1/parties/{id}/logo?v=<16 hex>`,
    );
  }
  return value;
}

function parseDatasetVersion(body: unknown): DatasetVersion {
  if (!isRecord(body)) {
    throw new ContractError("response body must be an object");
  }
  const path = "dataset_version";
  const id = requirePositiveInteger(body, "id", path);
  const electionId = requirePositiveInteger(body, "election_id", path);
  const createdAt = body["created_at"];
  if (typeof createdAt !== "string" || !TIMESTAMP_PATTERN.test(createdAt)) {
    throw new ContractError(`${path}.created_at must be YYYY-MM-DDTHH:MM:SSZ`);
  }
  const statements = parseStatements(body);
  const parties = requireArray(body, "parties", path).map((party, index) =>
    parseParty(party, `parties[${index}]`, statements),
  );
  const questionnaireLengths = parseQuestionnaireLengths(body, path, statements.length);
  return { id, electionId, createdAt, statements, parties, questionnaireLengths };
}

// `questionnaire_lengths` (pipeline-statement-priority-tiers): strictly
// increasing positive integers ending at the Statement count. A missing key
// (an older server) reads as the full length only.
function parseQuestionnaireLengths(
  body: Record<string, unknown>,
  path: string,
  statementCount: number,
): readonly number[] {
  if (!("questionnaire_lengths" in body)) {
    return [statementCount];
  }
  const raw = body["questionnaire_lengths"];
  const message =
    `${path}.questionnaire_lengths must be strictly increasing positive integers ` +
    `ending at the statement count (${statementCount})`;
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new ContractError(message);
  }
  let previous = 0;
  for (const value of raw) {
    if (typeof value !== "number" || !Number.isInteger(value) || value <= previous) {
      throw new ContractError(message);
    }
    previous = value;
  }
  if (previous !== statementCount) {
    throw new ContractError(message);
  }
  return [...raw] as number[];
}

function parseLegalHolder(value: unknown, path: string): LegalHolder {
  const item = requireRecord(value, path);
  const name = item["name"];
  if (typeof name !== "string" || name === "") {
    throw new ContractError(`${path}.name must be a non-empty string`);
  }
  const nif = item["nif"];
  if (nif !== null && (typeof nif !== "string" || nif === "")) {
    throw new ContractError(`${path}.nif must be null or a non-empty string`);
  }
  return { name, nif };
}

function parseLegalNotice(body: unknown): LegalNotice {
  const path = "legal_notice";
  const item = requireRecord(body, path);
  const holders = requireArray(item, "holders", path).map((holder, index) =>
    parseLegalHolder(holder, `holders[${index}]`),
  );
  const contactEmail = item["contact_email"];
  if (
    contactEmail !== null &&
    (typeof contactEmail !== "string" || !contactEmail.includes("@") || /\s/.test(contactEmail))
  ) {
    throw new ContractError(`${path}.contact_email must be null or an address with "@" and no spaces`);
  }
  const address = item["address"];
  if (address !== null && (typeof address !== "string" || address === "")) {
    throw new ContractError(`${path}.address must be null or a non-empty string`);
  }
  return { holders, contactEmail, address };
}

function parseDonation(body: unknown): string | null {
  const item = requireRecord(body, "donation");
  const url = item["url"];
  if (url === null || isDonationUrl(url)) {
    return url;
  }
  throw new ContractError(`donation.url must be null or ${DONATION_URL_FORMAT}`);
}

export function createPublicApiClient(options: PublicApiClientOptions): PublicApiClient {
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

  // Same error wrapping for every method: a contract violation is an
  // `invalid_response` naming the request path and the offending field.
  async function getParsed<T>(path: string, parse: (body: unknown) => T): Promise<T> {
    const body = await getJson(path);
    try {
      return parse(body);
    } catch (error) {
      if (error instanceof ContractError) {
        throw new PublicApiError("invalid_response", `GET ${path}: ${error.message}`);
      }
      throw error;
    }
  }

  // The only request with a body. Only `message`, `origin` and a non-empty
  // `website` are sent: never an Election, Dataset Version or Answers.
  async function sendFeedback(feedback: FeedbackInput): Promise<void> {
    const path = "/api/v1/feedback";
    const body: { message: string; origin: string; website?: string } = {
      message: feedback.message,
      origin: feedback.origin,
    };
    if (typeof feedback.website === "string" && feedback.website !== "") {
      body.website = feedback.website;
    }
    let response: HttpResponseLike;
    try {
      response = await fetchFn(`${baseUrl}${path}`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      throw new PublicApiError("network", `POST ${path} failed: network error`);
    }
    if (!response.ok) {
      throw new PublicApiError(
        "http",
        `POST ${path} failed: HTTP ${response.status}`,
        response.status,
      );
    }
  }

  return {
    sendFeedback,
    listElections() {
      return getParsed("/api/v1/elections", parseElectionList);
    },
    getElection(id: number) {
      return getParsed(`/api/v1/elections/${id}`, (body) => parseElection(body, "election"));
    },
    getDatasetVersion(id: number) {
      return getParsed(`/api/v1/dataset-versions/${id}`, parseDatasetVersion);
    },
    getLegalNotice() {
      return getParsed("/api/v1/legal-notice", parseLegalNotice);
    },
    getDonationUrl() {
      return getParsed("/api/v1/donation", parseDonation);
    },
  };
}
