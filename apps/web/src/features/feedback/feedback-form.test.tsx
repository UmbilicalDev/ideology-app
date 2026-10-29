import { describe, expect, test } from "vitest";

import { PublicApiError } from "@ideology-app/core";

import {
  counterText,
  errorText,
  limitAnnouncement,
  prepareFeedback,
  problemText,
} from "./feedback-form";

describe("prepareFeedback", () => {
  test("counts code points of the trimmed text, as the server does", () => {
    expect(prepareFeedback("hola ")).toMatchObject({ message: "hola", count: 4, problem: null });
    const emoji = "😀".repeat(500);
    expect(emoji.length).toBe(1000);
    expect(prepareFeedback(emoji)).toMatchObject({ count: 500, problem: null });
    expect(prepareFeedback("😀".repeat(501))).toMatchObject({ count: 501, problem: "too_long" });
  });

  test("empty or whitespace-only text is empty", () => {
    expect(prepareFeedback("").problem).toBe("empty");
    expect(prepareFeedback("   \n ").problem).toBe("empty");
  });

  test("tabs become spaces; other control characters are a problem", () => {
    expect(prepareFeedback("a\tb")).toMatchObject({ prepared: "a b", message: "a b", problem: null });
    expect(prepareFeedback("\ta\t").message).toBe("a");
    expect(prepareFeedback("a\u000Bb").problem).toBe("control_character");
    expect(prepareFeedback("a\nb").problem).toBeNull();
  });
});

describe("counterText", () => {
  test("is N/500", () => {
    expect(counterText(0)).toBe("0/500");
    expect(counterText(501)).toBe("501/500");
  });
});

describe("limitAnnouncement", () => {
  test.each([
    [0, ""],
    [449, ""],
    [450, "Quedan 50 caracteres o menos."],
    [474, "Quedan 50 caracteres o menos."],
    [475, "Quedan 25 caracteres o menos."],
    [489, "Quedan 25 caracteres o menos."],
    [490, "Quedan 10 caracteres o menos."],
    [499, "Quedan 10 caracteres o menos."],
    [500, "Has llegado al límite de 500 caracteres."],
    [501, "Has superado el límite de 500 caracteres."],
    [900, "Has superado el límite de 500 caracteres."],
  ])("%i characters -> %j", (count, text) => {
    expect(limitAnnouncement(count)).toBe(text);
  });
});

describe("problemText", () => {
  test("has a line for too long and invisible characters only", () => {
    expect(problemText("too_long")).toBe(
      "Has superado el límite de 500 caracteres. Borra texto para poder enviar.",
    );
    expect(problemText("control_character")).toBe(
      "El texto tiene caracteres invisibles que no se pueden enviar. Prueba a escribirlo en " +
        "lugar de pegarlo.",
    );
    expect(problemText("empty")).toBeNull();
    expect(problemText(null)).toBeNull();
  });
});

describe("errorText", () => {
  const GENERIC = "No se ha podido enviar tu opinión. Inténtalo de nuevo más tarde.";
  const REJECTED = "El servidor no ha aceptado el mensaje. Revisa el texto e inténtalo de nuevo.";
  test.each<[string, unknown, string]>([
    [
      "network",
      new PublicApiError("network", "x"),
      "No se ha podido enviar tu opinión. Comprueba tu conexión e inténtalo de nuevo.",
    ],
    [
      "429",
      new PublicApiError("http", "x", 429),
      "Se han enviado muchas opiniones en poco tiempo. Espera unos minutos e inténtalo de nuevo.",
    ],
    ["413", new PublicApiError("http", "x", 413), REJECTED],
    ["415", new PublicApiError("http", "x", 415), REJECTED],
    ["422", new PublicApiError("http", "x", 422), REJECTED],
    ["500", new PublicApiError("http", "x", 500), GENERIC],
    ["invalid_response", new PublicApiError("invalid_response", "x"), GENERIC],
    ["other error", new Error("x"), GENERIC],
  ])("%s", (_name, error, text) => {
    expect(errorText(error)).toBe(text);
  });
});
