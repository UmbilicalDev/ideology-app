// An Election as the public API describes it (`GET /api/v1/elections`).
// Keys are camelCase; the HTTP adapter maps the API's snake_case once.
export type ElectionStatus = "draft" | "active" | "archived";

/**
 * Which model a Dataset Version follows: `legacy` (read it whole with
 * `getDatasetVersion`) or `v2` (read it per Constituency through `ConstituencyApi`).
 */
export type DatasetVersionGeneration = "legacy" | "v2";

export interface Election {
  readonly id: number;
  readonly country: string;
  readonly type: string;
  /** Calendar date of the Election, `YYYY-MM-DD`. */
  readonly date: string;
  readonly name: string;
  readonly status: ElectionStatus;
  readonly publishedDatasetVersionId: number | null;
  /** `null` exactly when `publishedDatasetVersionId` is `null`. */
  readonly publishedDatasetVersionGeneration: DatasetVersionGeneration | null;
}
