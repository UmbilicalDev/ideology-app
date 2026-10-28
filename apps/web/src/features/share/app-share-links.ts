// Share targets for "Comparte IdeologiApp" (DESIGN.md "Share card").
// Pure: no React, window, navigator or location access. The caller passes
// `window.location.origin`; only the home URL built from it is ever shared,
// never a path, query, fragment, Dataset Version id or Answers
// (CONSTRAINTS.md, Client-side Matching).

export const SHARE_TEXT =
  "Compara tus opiniones con los programas electorales de los partidos en IdeologiApp.";

export const EMAIL_SUBJECT = "IdeologiApp: compara tus opiniones con los programas electorales";

export type AppShareLinks = {
  readonly home: string;
  readonly facebook: string;
  readonly whatsapp: string;
  readonly x: string;
  readonly email: string;
};

/** The IdeologiApp home URL for `origin`; any path, query or fragment is dropped. */
export function appHomeUrl(origin: string): string {
  return new URL("/", origin).href;
}

/** Every share target's URL, all carrying only the home URL (and fixed text). */
export function appShareLinks(origin: string): AppShareLinks {
  const home = appHomeUrl(origin);
  const enc = encodeURIComponent;
  return {
    home,
    facebook: `https://www.facebook.com/sharer/sharer.php?u=${enc(home)}`,
    whatsapp: `https://wa.me/?text=${enc(`${SHARE_TEXT} ${home}`)}`,
    x: `https://x.com/intent/post?url=${enc(home)}&text=${enc(SHARE_TEXT)}`,
    // RFC 6068: line breaks in a mailto body are CRLF, encoded as %0D%0A.
    email: `mailto:?subject=${enc(EMAIL_SUBJECT)}&body=${enc(`${SHARE_TEXT}\r\n\r\n${home}`)}`,
  };
}
