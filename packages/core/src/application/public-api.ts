// Port: the read-only public API as the clients use it. Implemented by
// `infrastructure/http/public-api-client.ts`; tests inject a mocked fetch.
import type { Election } from "../domain/election";

export interface PublicApi {
  /** Active Elections in API order (`date` desc, then `id` desc). */
  listElections(): Promise<readonly Election[]>;
}
