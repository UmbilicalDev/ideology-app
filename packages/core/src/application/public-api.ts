// Port: the read-only public API as the clients use it. Implemented by
// `infrastructure/http/public-api-client.ts`; tests inject a mocked fetch.
import type { DatasetVersion } from "../domain/dataset-version";
import type { Election } from "../domain/election";

export interface PublicApi {
  /** Active Elections in API order (`date` desc, then `id` desc). */
  listElections(): Promise<readonly Election[]>;
  /** Any Election by id, whatever its status (`GET /api/v1/elections/{id}`). */
  getElection(id: number): Promise<Election>;
  /** A public Dataset Version by id (`GET /api/v1/dataset-versions/{id}`); immutable. */
  getDatasetVersion(id: number): Promise<DatasetVersion>;
}
