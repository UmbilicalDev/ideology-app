import { describe, expect, expectTypeOf, test } from "vitest";

import { TOPIC_CATALOG, findTopic } from "../../src/index";
import type { TopicKey } from "../../src/index";

// The catalog is generated from src/ideology_app/topic_catalog.py
// (tests/test_topic_catalog.py checks the generated file matches it).
describe("TOPIC_CATALOG", () => {
  test("has 18 entries with orders 1..18 ascending", () => {
    expect(TOPIC_CATALOG).toHaveLength(18);
    expect(TOPIC_CATALOG.map((entry) => entry.order)).toEqual(
      Array.from({ length: 18 }, (_, i) => i + 1),
    );
  });

  test("every entry has a non-empty unique name and key", () => {
    for (const entry of TOPIC_CATALOG) {
      expect(entry.name.trim()).not.toBe("");
      expect(entry.key).toMatch(/^[a-z_]+$/);
    }
    expect(new Set(TOPIC_CATALOG.map((entry) => entry.name)).size).toBe(18);
    expect(new Set(TOPIC_CATALOG.map((entry) => entry.key)).size).toBe(18);
  });

  test("starts with the topics citizens name most and ends with the unranked one", () => {
    expect(TOPIC_CATALOG[0]).toEqual({ key: "housing", name: "Vivienda", order: 1 });
    expect(TOPIC_CATALOG[17]).toEqual({
      key: "culture_language",
      name: "Cultura y lenguas",
      order: 18,
    });
  });

  test("TopicKey is the union of the catalog keys", () => {
    expectTypeOf<"housing">().toExtend<TopicKey>();
    expectTypeOf<TopicKey>().toEqualTypeOf<(typeof TOPIC_CATALOG)[number]["key"]>();
  });
});

describe("findTopic", () => {
  test("returns the entry for a catalog key", () => {
    expect(findTopic("housing")?.name).toBe("Vivienda");
    expect(findTopic("science_digital")).toEqual({
      key: "science_digital",
      name: "Ciencia y digitalización",
      order: 15,
    });
  });

  test("returns undefined for an unknown key", () => {
    expect(findTopic("economía")).toBeUndefined();
    expect(findTopic("")).toBeUndefined();
    expect(findTopic("Housing")).toBeUndefined();
  });
});
