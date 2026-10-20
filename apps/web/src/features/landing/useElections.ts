import { useCallback, useEffect, useState } from "react";

import type { Election, PublicApi } from "@ideology-app/core";

export type ElectionsState =
  | { readonly kind: "loading" }
  | { readonly kind: "loaded"; readonly elections: readonly Election[] }
  | { readonly kind: "error" };

const LOADING: ElectionsState = { kind: "loading" };

/** Loads the active Elections once per mount; `retry` loads them again. */
export function useElections(api: PublicApi): {
  readonly state: ElectionsState;
  readonly retry: () => void;
} {
  const [state, setState] = useState<ElectionsState>(LOADING);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    api.listElections().then(
      (elections) => {
        if (active) {
          setState({ kind: "loaded", elections });
        }
      },
      () => {
        // Every PublicApiError kind shows the same message; nothing is logged.
        if (active) {
          setState({ kind: "error" });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [api, attempt]);

  const retry = useCallback(() => {
    setState(LOADING);
    setAttempt((n) => n + 1);
  }, []);

  return { state, retry };
}
