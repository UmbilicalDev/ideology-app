// Plain function tests of the pure builder (the web Vitest project only
// includes *.test.tsx files); nothing is rendered.
import { describe, expect, test } from "vitest";

import { appHomeUrl, appShareLinks, EMAIL_SUBJECT, SHARE_TEXT } from "./app-share-links";

const ORIGIN = "https://ideologiapp.example";
const HOME = "https://ideologiapp.example/";

describe("appHomeUrl", () => {
  test("is the origin plus '/'", () => {
    expect(appHomeUrl(ORIGIN)).toBe(HOME);
    expect(appHomeUrl("http://127.0.0.1:8021")).toBe("http://127.0.0.1:8021/");
  });

  test("drops any path, query or fragment passed in", () => {
    expect(appHomeUrl("https://ideologiapp.example/resultados?x=1#v1-1-dddddA")).toBe(HOME);
    expect(appHomeUrl("https://ideologiapp.example/elecciones/1/cuestionario")).toBe(HOME);
  });
});

describe("appShareLinks", () => {
  const links = appShareLinks(ORIGIN);

  test("builds the exact target URLs", () => {
    expect(links).toEqual({
      home: HOME,
      facebook: "https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fideologiapp.example%2F",
      whatsapp:
        "https://wa.me/?text=Compara%20tus%20opiniones%20con%20los%20programas%20electorales%20de%20" +
        "los%20partidos%20en%20IdeologiApp.%20https%3A%2F%2Fideologiapp.example%2F",
      x:
        "https://x.com/intent/post?url=https%3A%2F%2Fideologiapp.example%2F&text=Compara%20tus%20" +
        "opiniones%20con%20los%20programas%20electorales%20de%20los%20partidos%20en%20IdeologiApp.",
      email:
        "mailto:?subject=IdeologiApp%3A%20compara%20tus%20opiniones%20con%20los%20programas%20" +
        "electorales&body=Compara%20tus%20opiniones%20con%20los%20programas%20electorales%20de%20" +
        "los%20partidos%20en%20IdeologiApp.%0D%0A%0D%0Ahttps%3A%2F%2Fideologiapp.example%2F",
    });
  });

  test("decoding each link's parameters returns the home URL and the fixed text", () => {
    const facebook = new URL(links.facebook);
    expect(facebook.origin + facebook.pathname).toBe("https://www.facebook.com/sharer/sharer.php");
    expect([...facebook.searchParams.keys()]).toEqual(["u"]);
    expect(facebook.searchParams.get("u")).toBe(HOME);

    const whatsapp = new URL(links.whatsapp);
    expect(whatsapp.origin + whatsapp.pathname).toBe("https://wa.me/");
    expect([...whatsapp.searchParams.keys()]).toEqual(["text"]);
    expect(whatsapp.searchParams.get("text")).toBe(`${SHARE_TEXT} ${HOME}`);

    const x = new URL(links.x);
    expect(x.origin + x.pathname).toBe("https://x.com/intent/post");
    expect([...x.searchParams.keys()]).toEqual(["url", "text"]);
    expect(x.searchParams.get("url")).toBe(HOME);
    expect(x.searchParams.get("text")).toBe(SHARE_TEXT);

    expect(links.email.startsWith("mailto:?")).toBe(true);
    const email = new URLSearchParams(links.email.slice("mailto:?".length));
    expect([...email.keys()]).toEqual(["subject", "body"]);
    expect(email.get("subject")).toBe(EMAIL_SUBJECT);
    expect(email.get("body")).toBe(`${SHARE_TEXT}\r\n\r\n${HOME}`);
  });

  test("the mailto encodes spaces as %20, never '+', and line breaks as %0D%0A", () => {
    expect(links.email).toContain("%20");
    expect(links.email).not.toContain("+");
    expect(links.email).toContain("%0D%0A%0D%0A");
    for (const url of Object.values(links)) {
      expect(url).not.toContain("+");
    }
  });

  test("no output carries a fragment, a result path or Answers, whatever origin string is given", () => {
    const leaky = appShareLinks("https://ideologiapp.example/resultados?x=1#v1-1-dddddA");
    expect(leaky).toEqual(links);
    for (const url of Object.values(leaky)) {
      expect(url).not.toContain("#");
      expect(url).not.toContain("resultados");
      expect(url).not.toContain("v1-");
      expect(url).not.toContain("dddddA");
    }
  });
});
