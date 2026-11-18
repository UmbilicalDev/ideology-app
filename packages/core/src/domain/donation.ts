// The project's donation link (donate-buymeacoffee), as served by
// `GET /api/v1/donation` from the server's `DONATION_URL`. The same rule lives
// in `src/ideology_app/config.py` (`DONATION_URL_RE`); the shared vectors in
// both test suites keep them equal. The web client uses the href verbatim, so
// the client checks it again (defence in depth).

/** `https://www.buymeacoffee.com/<perfil>` or `https://buymeacoffee.com/<perfil>`, profile `[A-Za-z0-9_-]{1,64}`. */
export const DONATION_URL_PATTERN = /^https:\/\/(www\.)?buymeacoffee\.com\/[A-Za-z0-9_-]{1,64}$/;

/** The accepted forms, for messages. */
export const DONATION_URL_FORMAT = "https://www.buymeacoffee.com/<perfil> or https://buymeacoffee.com/<perfil>";

/** True when `value` is a string that fully matches `DONATION_URL_PATTERN`. */
export function isDonationUrl(value: unknown): value is string {
  return typeof value === "string" && DONATION_URL_PATTERN.test(value);
}
