import { describe, expect, test } from "vitest";

import { DONATION_URL_PATTERN, isDonationUrl } from "../../src/index";

// The same vectors as `tests/test_donation.py` (donate-buymeacoffee). The
// server trims the setting first; the client checks the value it receives as is.
const ACCEPTED: readonly string[] = [
  "https://www.buymeacoffee.com/perfil_de_prueba",
  "https://buymeacoffee.com/perfil_de_prueba",
  "https://www.buymeacoffee.com/Perfil-2",
  "https://buymeacoffee.com/Perfil-2",
  "https://www.buymeacoffee.com/" + "a".repeat(64),
];

const REFUSED: readonly string[] = [
  "http://www.buymeacoffee.com/perfil_de_prueba",
  "http://buymeacoffee.com/perfil_de_prueba",
  "https://www.buymeacoffee.com/",
  "https://buymeacoffee.com/",
  "https://m.buymeacoffee.com/perfil",
  "https://wwwbuymeacoffee.com/perfil",
  "https://buymeacoffee.com.evil.test/perfil",
  "https://BuyMeACoffee.com/perfil",
  "https://www.buymeacoffee.com/perfil_de_prueba/",
  "https://www.buymeacoffee.com/a/b",
  "https://www.buymeacoffee.com/perfil?ref=x",
  "https://www.buymeacoffee.com/perfil#x",
  "https://WWW.BUYMEACOFFEE.COM/perfil",
  "https://www.buymeacoffee.com.evil.test/perfil",
  "https://www.buymeacoffee.com@evil.test/perfil",
  "https://www.buymeacoffee.com:443/perfil",
  "https://www.buymeacoffee.com/perfil%20x",
  "https://www.buymeacoffee.com/perfíl",
  "https://www.buymeacoffee.com/" + "a".repeat(65),
  "https://www.buymeacoffee.com/perfil\nx",
  "javascript:alert(1)",
  // Client only: the server trims, the client never does.
  " https://www.buymeacoffee.com/perfil_de_prueba",
  "https://www.buymeacoffee.com/perfil_de_prueba\n",
];

describe("isDonationUrl", () => {
  test.each(ACCEPTED)("accepts %s", (value) => {
    expect(isDonationUrl(value)).toBe(true);
    expect(DONATION_URL_PATTERN.test(value)).toBe(true);
  });

  test.each(REFUSED)("refuses %j", (value) => {
    expect(isDonationUrl(value)).toBe(false);
  });

  test.each([null, undefined, 1, {}, ["https://www.buymeacoffee.com/perfil_de_prueba"]])(
    "refuses the non-string %j",
    (value) => {
      expect(isDonationUrl(value)).toBe(false);
    },
  );
});
