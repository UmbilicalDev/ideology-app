// An Election as the public API describes it (`GET /api/v1/elections`).
// Keys are camelCase; the HTTP adapter maps the API's snake_case once.
export type ElectionStatus = "draft" | "active" | "archived";

export interface Election {
  readonly id: number;
  readonly country: string;
  readonly type: string;
  /** Calendar date of the Election, `YYYY-MM-DD`. */
  readonly date: string;
  readonly name: string;
  readonly status: ElectionStatus;
  readonly publishedDatasetVersionId: number | null;
}
