import { useEffect, useState } from "react";

/** How long a copy button shows `¡Copiado!` before it goes back. */
export const COPIED_FLASH_MS = 2000;

/**
 * A copy button's short `¡Copiado!` state: `flash()` turns it on and it
 * turns itself off after `COPIED_FLASH_MS`; another copy restarts the wait.
 */
export function useCopiedFlash(): readonly [boolean, () => void] {
  const [stamp, setStamp] = useState(0);

  useEffect(() => {
    if (stamp === 0) return;
    const timer = setTimeout(() => setStamp(0), COPIED_FLASH_MS);
    return () => clearTimeout(timer);
  }, [stamp]);

  return [stamp !== 0, () => setStamp((previous) => previous + 1)];
}
