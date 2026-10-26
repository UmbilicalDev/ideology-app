import { useCallback, useEffect, useState } from "react";

import { openShareLink, type OpenShareLinkResult, type PublicApi } from "@ideology-app/core";

import { preloadPartyLogos } from "../results/party-logo-preload";

export type SharedResultState = { readonly kind: "loading" } | OpenShareLinkResult;

const LOADING: SharedResultState = { kind: "loading" };

/**
 * Opens the Share Link `fragment` (text after "#") once per mount through
 * `openShareLink`; `retry` repeats it (decode and both requests). Stale
 * results are ignored and nothing is logged. A `ready` result preloads its
 * Party logos in Dataset Version order before it renders, so the logo
 * requests never follow the (answer-derived) ranking.
 */
export function useSharedResult(
  api: PublicApi,
  fragment: string,
): { readonly state: SharedResultState; readonly retry: () => void } {
  const [state, setState] = useState<SharedResultState>(LOADING);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    openShareLink(api, fragment).then(
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
  }, [api, fragment, attempt]);

  const retry = useCallback(() => {
    setState(LOADING);
    setAttempt((n) => n + 1);
  }, []);

  return { state, retry };
}
