// A v2 Dataset Version read one Constituency at a time (public-dataset-api-v2):
// `GET /api/v1/dataset-versions/{id}/constituencies[/{code}[/proposals/{category}]]`.
// Keys are camelCase; the HTTP adapter maps the API's snake_case once, checks
// the contract and resolves Evidence ids into `Proposal` objects. The server
// already applied S5: a value and its Evidence are the Party's in that
// Constituency, so a client never filters by Constituency itself.
import type { NO_STANCE, ScaleValue } from "./match-score";
import type { TopicKey } from "./topics";

/** An INE province code: exactly two digits, e.g. `"28"` (Madrid). */
export const CONSTITUENCY_CODE_PATTERN = /^[0-9]{2}$/;

export function isConstituencyCode(value: unknown): value is string {
  return typeof value === "string" && CONSTITUENCY_CODE_PATTERN.test(value);
}

/** Why a Constituency is unavailable: the first rule that fails. */
export type UnavailableReason =
  | "fewer_than_two_parties"
  | "too_few_statements"
  | "low_party_coverage";

export const UNAVAILABLE_REASONS: readonly UnavailableReason[] = [
  "fewer_than_two_parties",
  "too_few_statements",
  "low_party_coverage",
];

/** Why an Excluded Party has no Positions. */
export type ExcludedReason = "no_manifesto" | "discarded_at_review" | "too_few_proposals";

export const EXCLUDED_REASONS: readonly ExcludedReason[] = [
  "no_manifesto",
  "discarded_at_review",
  "too_few_proposals",
];

export interface ConstituencySummary {
  readonly code: string;
  readonly name: string;
  readonly available: boolean;
  /** `null` exactly when `available`. */
  readonly unavailableReason: UnavailableReason | null;
  readonly validStatementCount: number;
  /** Ascending; empty when unavailable. */
  readonly offeredLengths: readonly number[];
}

/** Every Constituency of a v2 Dataset Version (52, in code order). */
export interface ConstituencyList {
  readonly id: number;
  readonly electionId: number;
  /** UTC, `YYYY-MM-DDTHH:MM:SSZ`. */
  readonly createdAt: string;
  readonly constituencies: readonly ConstituencySummary[];
}

export interface ConstituencyStatement {
  readonly id: number;
  /** 1-based priority in the Constituency; a questionnaire of length L is ranks 1..L. */
  readonly rank: number;
  /** The final text (never the AI text of a reworded Statement). */
  readonly text: string;
  readonly topic: string;
  readonly contextNote: string | null;
}

/** A verbatim measure of a manifesto, on the page it starts on. */
export interface Proposal {
  readonly id: number;
  readonly text: string;
  readonly page: number;
  /** The Source Document's URL for URL documents, `null` otherwise. */
  readonly url: string | null;
  /** The Party's own Source Document (a shared manifesto differs per Party). */
  readonly sourceDocumentId: number;
}

export interface ConstituencyPosition {
  readonly statementId: number;
  /** The Party's value in this Constituency (S5, applied by the server). */
  readonly value: ScaleValue | typeof NO_STANCE;
  /** The Evidence Proposals that count here, in rank order; empty exactly when `no_stance`. */
  readonly evidence: readonly Proposal[];
}

export interface ConstituencyParty {
  readonly id: number;
  readonly name: string;
  readonly shortName: string;
  /** Same-origin logo path, or `null`. */
  readonly logoUrl: string | null;
  /** One entry per Statement, in Statement order; empty when unavailable. */
  readonly positions: readonly ConstituencyPosition[];
}

export interface ExcludedParty {
  readonly id: number;
  readonly name: string;
  readonly shortName: string;
  readonly reason: ExcludedReason;
}

/** One Constituency of a v2 Dataset Version. */
export interface ConstituencyQuestionnaire {
  readonly datasetVersionId: number;
  readonly code: string;
  readonly name: string;
  readonly available: boolean;
  readonly unavailableReason: UnavailableReason | null;
  /** Ascending; empty when unavailable. */
  readonly offeredLengths: readonly number[];
  /** In rank order; empty when unavailable. */
  readonly statements: readonly ConstituencyStatement[];
  /** The non-Excluded Parties running here, by id. */
  readonly parties: readonly ConstituencyParty[];
  /** The Excluded Parties running here, by id. */
  readonly excludedParties: readonly ExcludedParty[];
}

export interface PartyProposals {
  readonly partyId: number;
  /** Counted here and carrying the category, in counted order; may be empty. */
  readonly proposals: readonly Proposal[];
}

/** Each running Party's Proposals in one category (Comparador). */
export interface ConstituencyProposals {
  readonly datasetVersionId: number;
  readonly code: string;
  readonly category: TopicKey;
  /** Every non-Excluded Party running here, by id, empty lists included. */
  readonly parties: readonly PartyProposals[];
}
