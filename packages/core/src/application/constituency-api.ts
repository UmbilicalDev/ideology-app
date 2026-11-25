// Port: the v2 Dataset Version routes of the public API, one Constituency at a
// time (public-dataset-api-v2). Kept apart from `PublicApi` so existing fakes
// keep compiling. Implemented by `infrastructure/http/public-api-client.ts`.
// Every request is a GET with path parameters only: no Answer is ever sent.
import type {
  ConstituencyList,
  ConstituencyProposals,
  ConstituencyQuestionnaire,
} from "../domain/constituency";
import type { TopicKey } from "../domain/topics";

export interface ConstituencyApi {
  /** The 52 Constituencies of a v2 Dataset Version, in code order; immutable. */
  listConstituencies(versionId: number): Promise<ConstituencyList>;
  /** One Constituency's ranked Statements and Parties (S5 applied); immutable. */
  getConstituencyQuestionnaire(versionId: number, code: string): Promise<ConstituencyQuestionnaire>;
  /** Each running Party's Proposals in one category there (Comparador); immutable. */
  getConstituencyProposals(
    versionId: number,
    code: string,
    category: TopicKey,
  ): Promise<ConstituencyProposals>;
}
