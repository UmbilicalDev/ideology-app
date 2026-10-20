export {
  IMPORTANT_WEIGHT,
  LOW_COVERAGE_THRESHOLD,
  NO_STANCE,
  SKIP,
  computeMatchScore,
  computeMatchScores,
  statementAgreement,
} from "./domain/match-score";
export type {
  Answer,
  MatchScoreOptions,
  MatchScoreResult,
  PartyInput,
  PositionInput,
  ScaleValue,
  StatementId,
} from "./domain/match-score";
export type { Election, ElectionStatus } from "./domain/election";
export type {
  DatasetVersion,
  Evidence,
  Party,
  PartyPosition,
  Statement,
} from "./domain/dataset-version";
export {
  currentStatementId,
  isAtEnd,
  reduceQuestionnaire,
  startQuestionnaire,
  summarize,
  toMatchScoreAnswers,
} from "./domain/questionnaire";
export type {
  AnswerValue,
  QuestionnaireAction,
  QuestionnaireState,
  QuestionnaireSummary,
} from "./domain/questionnaire";
export { buildBreakdown, evidenceHref } from "./domain/breakdown";
export type { BreakdownPosition, BreakdownRow, EvidenceView } from "./domain/breakdown";
export { rankParties } from "./domain/ranking";
export type { RankedParty } from "./domain/ranking";
export { buildResults } from "./domain/results";
export type { Results } from "./domain/results";
export { isQuestionnaireAvailable, sharedVersionStatus } from "./domain/shared-result";
export type { SharedVersionStatus } from "./domain/shared-result";
export type { PublicApi } from "./application/public-api";
export { openShareLink } from "./application/open-share-link";
export type { OpenShareLinkResult } from "./application/open-share-link";
export { PublicApiError, createPublicApiClient } from "./infrastructure/http/public-api-client";
export type {
  FetchLike,
  HttpResponseLike,
  PublicApiClientOptions,
  PublicApiErrorKind,
} from "./infrastructure/http/public-api-client";
export {
  MAX_SHARE_LINK_STATEMENTS,
  SHARE_LINK_FORMAT_VERSION,
  ShareLinkError,
  decodeShareLink,
  encodeShareLink,
  restoreQuestionnaire,
} from "./infrastructure/share-link/share-link-codec";
export type {
  ShareLink,
  ShareLinkEntry,
  ShareLinkErrorKind,
} from "./infrastructure/share-link/share-link-codec";
