// A Dataset Version as the public API describes it
// (`GET /api/v1/dataset-versions/{id}`). Keys are camelCase; the HTTP adapter
// maps the API's snake_case once and checks the contract.
import type { NO_STANCE, ScaleValue } from "./match-score";

export interface Statement {
  readonly id: number;
  /** 1-based display order; the API sends Statements in this order. */
  readonly position: number;
  readonly text: string;
  readonly topic: string;
}

export interface Evidence {
  readonly quote: string;
  readonly page: number;
  /** The Source Document's URL for URL documents, `null` for uploads. */
  readonly url: string | null;
  readonly sourceDocumentId: number;
}

export interface PartyPosition {
  readonly statementId: number;
  readonly value: ScaleValue | typeof NO_STANCE;
  /** `null` exactly when `value` is `no_stance`. */
  readonly evidence: Evidence | null;
}

export interface Party {
  readonly id: number;
  readonly name: string;
  readonly shortName: string;
  /** One entry per Statement, in Statement order. */
  readonly positions: readonly PartyPosition[];
}

export interface DatasetVersion {
  readonly id: number;
  readonly electionId: number;
  /** UTC, `YYYY-MM-DDTHH:MM:SSZ`. */
  readonly createdAt: string;
  readonly statements: readonly Statement[];
  readonly parties: readonly Party[];
}
