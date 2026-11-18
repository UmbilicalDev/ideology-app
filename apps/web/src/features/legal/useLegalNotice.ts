import { useCallback, useEffect, useState } from "react";

import type { LegalNotice, PublicApi } from "@ideology-app/core";

export type LegalNoticeState =
  | { readonly kind: "loading" }
  | { readonly kind: "loaded"; readonly notice: LegalNotice }
  | { readonly kind: "error" };

const LOADING: LegalNoticeState = { kind: "loading" };

/** Loads the holders and contact once per mount; `retry` loads them again. */
export function useLegalNotice(api: PublicApi): {
  readonly state: LegalNoticeState;
  readonly retry: () => void;
} {
  const [state, setState] = useState<LegalNoticeState>(LOADING);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    api.getLegalNotice().then(
      (notice) => {
        if (active) {
          setState({ kind: "loaded", notice });
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
