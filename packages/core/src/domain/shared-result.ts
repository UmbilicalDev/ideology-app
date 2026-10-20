// How a shared result's pinned Dataset Version relates to its Election now.
// Pure: no React, DOM, storage or network.
import type { Election } from "./election";

/**
 * `current`: the link pins the Election's Published Dataset Version.
 * `superseded`: another version has been published since.
 * `no_current`: the Election has no Published Dataset Version.
 */
export type SharedVersionStatus = "current" | "superseded" | "no_current";

export function sharedVersionStatus(
  election: Pick<Election, "publishedDatasetVersionId">,
  datasetVersionId: number,
): SharedVersionStatus {
  if (election.publishedDatasetVersionId === null) {
    return "no_current";
  }
  return election.publishedDatasetVersionId === datasetVersionId ? "current" : "superseded";
}

/** Whether the Election's current Questionnaire can be offered: `active` with a Published version. */
export function isQuestionnaireAvailable(
  election: Pick<Election, "status" | "publishedDatasetVersionId">,
): boolean {
  return election.status === "active" && election.publishedDatasetVersionId !== null;
}
