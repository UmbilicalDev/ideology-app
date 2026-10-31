import { useEffect, useState } from "react";

/**
 * Whether a media query matches, kept in sync with the window. `false` where
 * `matchMedia` does not exist (jsdom), so tests get the compact layout unless
 * they stub it.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const list = window.matchMedia?.(query);
    if (list === undefined) {
      return;
    }
    const onChange = () => setMatches(list.matches);
    onChange();
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
