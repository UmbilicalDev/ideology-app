import { useCallback, useEffect, useState } from "react";

import { openShareLink, type OpenShareLinkResult, type PublicApi } from "@ideology-app/core";

export type SharedResultState = { readonly kind: "loading" } | OpenShareLinkResult;

const LOADING: SharedResultState = { kind: "loading" };

/**
 * Opens the Share Link `fragment` (text after "#") once per mount through
 * `openShareLink`; `retry` repeats it (decode and both requests). Stale
 * results are ignored and nothing is logged.
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
