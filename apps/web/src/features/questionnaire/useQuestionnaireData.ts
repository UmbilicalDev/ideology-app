import { useCallback, useEffect, useState } from "react";

import { PublicApiError, type DatasetVersion, type Election, type PublicApi } from "@ideology-app/core";

import { preloadPartyLogos } from "../results/party-logo-preload";

export type QuestionnaireDataState =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly election: Election;
      readonly datasetVersion: DatasetVersion;
    }
  | { readonly kind: "unavailable" }
  | { readonly kind: "not_found" }
  | { readonly kind: "error" };

const LOADING: QuestionnaireDataState = { kind: "loading" };

async function load(api: PublicApi, electionId: number): Promise<QuestionnaireDataState> {
  let election: Election;
  try {
    election = await api.getElection(electionId);
  } catch (error) {
    if (error instanceof PublicApiError && error.kind === "http" && error.status === 404) {
      return { kind: "not_found" };
    }
    return { kind: "error" };
  }
  if (election.publishedDatasetVersionId === null) {
    return { kind: "unavailable" };
  }
  let datasetVersion: DatasetVersion;
  try {
    // Pinned by id: a publish during the session does not change the Statements.
    datasetVersion = await api.getDatasetVersion(election.publishedDatasetVersionId);
  } catch {
    return { kind: "error" };
  }
  if (datasetVersion.electionId !== electionId) {
    return { kind: "error" };
  }
  if (datasetVersion.statements.length === 0) {
    return { kind: "unavailable" };
  }
  return { kind: "ready", election, datasetVersion };
}

/**
 * Loads the Election, then its Published Dataset Version by id, once per
 * mount; `retry` repeats both requests. When the version is ready, its Party
 * logos are preloaded in Party order (`preloadPartyLogos`). These are the
 * page's only requests, and all happen before the first Answer. Nothing is
 * logged.
 */
export function useQuestionnaireData(
  api: PublicApi,
  electionId: number,
): { readonly state: QuestionnaireDataState; readonly retry: () => void } {
  const [state, setState] = useState<QuestionnaireDataState>(LOADING);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    load(api, electionId).then(
      (next) => {
        if (active) {
          if (next.kind === "ready") {
            preloadPartyLogos(next.datasetVersion.parties);
          }
          setState(next);
        }
      },
      () => {
        if (active) {
          setState({ kind: "error" });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [api, electionId, attempt]);

  const retry = useCallback(() => {
    setState(LOADING);
    setAttempt((n) => n + 1);
  }, []);

  return { state, retry };
}
