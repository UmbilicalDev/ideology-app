import { useEffect, useState } from "react";

import type { PublicApi } from "@ideology-app/core";

/**
 * Loads the donation link once per mount (donate-buymeacoffee): one bare
 * `GET /api/v1/donation`, which carries nothing and never depends on the
 * Answers. `null` while loading, on any error and when unset; a stale result
 * is ignored, nothing is logged and there is no retry.
 */
export function useDonationUrl(api: PublicApi): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.getDonationUrl().then(
      (value) => {
        if (active) {
          setUrl(value);
        }
      },
      () => {
        if (active) {
          setUrl(null);
        }
      },
    );
    return () => {
      active = false;
    };
  }, [api]);

  return url;
}
