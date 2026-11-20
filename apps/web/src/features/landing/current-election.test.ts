import { describe, expect, test } from "vitest";

import type { Election } from "@ideology-app/core";

import { currentElection } from "./current-election";

function election(id: number, date: string): Election {
  return {
    id,
    country: "ES",
    type: "general",
    date,
    name: `Generales ${date.slice(0, 4)}`,
    status: "active",
    publishedDatasetVersionId: id,
  };
}

describe("currentElection", () => {
  test("an empty list has no current Election", () => {
    expect(currentElection([])).toBeNull();
  });

  test("a single Election is the current one", () => {
    const only = election(1, "2023-07-23");
    expect(currentElection([only])).toBe(only);
  });

  test("picks the latest date whatever the input order", () => {
    const e2023 = election(1, "2023-07-23");
    const e2026 = election(2, "2026-11-29");
    const e2027 = election(3, "2027-07-01");
    for (const order of [
      [e2023, e2026, e2027],
      [e2027, e2023, e2026],
      [e2026, e2027, e2023],
    ]) {
      expect(currentElection(order)).toBe(e2027);
    }
  });

  test("on equal dates the higher id wins", () => {
    const low = election(4, "2026-11-29");
    const high = election(7, "2026-11-29");
    expect(currentElection([high, low])).toBe(high);
    expect(currentElection([low, high])).toBe(high);
  });

  test("compares within a year by month and day", () => {
    const july = election(9, "2026-07-01");
    const november = election(2, "2026-11-29");
    expect(currentElection([november, july])).toBe(november);
  });
});
