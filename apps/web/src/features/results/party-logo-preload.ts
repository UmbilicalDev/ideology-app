// Preloads the Party logos of a Dataset Version in its Party order (by id),
// as soon as the version is loaded and before any result renders
// (CONSTRAINTS.md, Party Logos). If the results' <img> elements fetched the
// logos first, the requests would reach the server in ranking order, and the
// ranking is derived from the Answers. The rendered <img> elements then get
// the bytes from this in-flight request or the HTTP cache (immutable).
//
// Logos are requested only through `Image` with the exact `logoUrl`, never
// with `fetch`. Images are kept in a module-level map so each URL is
// requested once and is not garbage-collected mid-load.

const preloaded = new Map<string, HTMLImageElement>();

export function preloadPartyLogos(parties: readonly { readonly logoUrl: string | null }[]): void {
  if (typeof Image === "undefined") return;
  for (const party of parties) {
    const url = party.logoUrl;
    if (url === null || preloaded.has(url)) continue;
    const image = new Image();
    image.decoding = "async";
    image.src = url;
    preloaded.set(url, image);
  }
}

/** Test helper: forget every preloaded URL. */
export function forgetPreloadedPartyLogos(): void {
  preloaded.clear();
}
