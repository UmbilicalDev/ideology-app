// Use case: open a Share Link. Decodes the fragment, loads the pinned
// Dataset Version and its Election through the `PublicApi` port, restores the
// end-screen Questionnaire state and computes the results with
// `buildResults`, the same path as the end screen. Pure apart from the port:
// no React, DOM, storage or logging. Requests carry only the Dataset Version
// id and the Election id (path parameters), never Answers.
import type { DatasetVersion } from "../domain/dataset-version";
import type { Election } from "../domain/election";
import type { QuestionnaireState } from "../domain/questionnaire";
import { buildResults, type Results } from "../domain/results";
import {
  isQuestionnaireAvailable,
  sharedVersionStatus,
  type SharedVersionStatus,
} from "../domain/shared-result";
import { PublicApiError } from "../infrastructure/http/public-api-client";
import {
  ShareLinkError,
  decodeShareLink,
  restoreQuestionnaire,
  type ShareLink,
  type ShareLinkErrorKind,
} from "../infrastructure/share-link/share-link-codec";
import type { PublicApi } from "./public-api";

export type OpenShareLinkResult =
  | { readonly kind: "missing" }
  | { readonly kind: "invalid"; readonly reason: ShareLinkErrorKind }
  | { readonly kind: "not_found" }
  | { readonly kind: "error" }
  | {
      readonly kind: "ready";
      readonly election: Election;
      readonly datasetVersion: DatasetVersion;
      readonly state: QuestionnaireState;
      readonly results: Results;
      readonly versionStatus: SharedVersionStatus;
      readonly questionnaireAvailable: boolean;
    };

const NOT_FOUND: OpenShareLinkResult = { kind: "not_found" };
const ERROR: OpenShareLinkResult = { kind: "error" };

function isNotFound(error: unknown): boolean {
  return error instanceof PublicApiError && error.kind === "http" && error.status === 404;
}

/**
 * The shared result for `fragment` (the text after "#", untrusted). Never
 * returns partial data and never throws: every failure is a result kind.
 */
export async function openShareLink(api: PublicApi, fragment: string): Promise<OpenShareLinkResult> {
  if (fragment === "") {
    return { kind: "missing" };
  }
  let link: ShareLink;
  try {
    link = decodeShareLink(fragment);
  } catch (error) {
    return error instanceof ShareLinkError ? { kind: "invalid", reason: error.kind } : ERROR;
  }
  try {
    return await load(api, link);
  } catch {
    // e.g. an engine RangeError on unexpected data.
    return ERROR;
  }
}

async function load(api: PublicApi, link: ShareLink): Promise<OpenShareLinkResult> {
  let datasetVersion: DatasetVersion;
  try {
    datasetVersion = await api.getDatasetVersion(link.datasetVersionId);
  } catch (error) {
    return isNotFound(error) ? NOT_FOUND : ERROR;
  }
  if (datasetVersion.id !== link.datasetVersionId) {
    return ERROR;
  }
  let state: QuestionnaireState;
  try {
    state = restoreQuestionnaire(
      link,
      datasetVersion.statements.map((statement) => statement.id),
    );
  } catch (error) {
    return error instanceof ShareLinkError ? { kind: "invalid", reason: error.kind } : ERROR;
  }
  let election: Election;
  try {
    election = await api.getElection(datasetVersion.electionId);
  } catch (error) {
    return isNotFound(error) ? NOT_FOUND : ERROR;
  }
  if (election.id !== datasetVersion.electionId) {
    return ERROR;
  }
  return {
    kind: "ready",
    election,
    datasetVersion,
    state,
    results: buildResults(datasetVersion, state),
    versionStatus: sharedVersionStatus(election, datasetVersion.id),
    questionnaireAvailable: isQuestionnaireAvailable(election),
  };
}
