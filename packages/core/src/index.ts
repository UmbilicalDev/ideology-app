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
} from "./domain/questionnaire";
export type {
  AnswerValue,
  QuestionnaireAction,
  QuestionnaireState,
  QuestionnaireSummary,
} from "./domain/questionnaire";
export type { PublicApi } from "./application/public-api";
export { PublicApiError, createPublicApiClient } from "./infrastructure/http/public-api-client";
export type {
  FetchLike,
  HttpResponseLike,
  PublicApiClientOptions,
  PublicApiErrorKind,
} from "./infrastructure/http/public-api-client";
