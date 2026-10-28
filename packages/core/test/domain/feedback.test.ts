import { describe, expect, test } from "vitest";

import {
  FEEDBACK_MAX_CHARS,
  countFeedbackChars,
  feedbackProblem,
  trimFeedback,
  type FeedbackProblem,
} from "../../src/index";

// The same vectors as `tests/test_feedback_message.py` (feedback-api,
// Scenario 2): a string is the text the server stores, otherwise the problem.
const VECTORS: readonly (readonly [string, string | FeedbackProblem, string])[] = [
  ["x".repeat(500), "x".repeat(500), "500 ASCII"],
  ["\u{1F600}".repeat(500), "\u{1F600}".repeat(500), "500 emoji (1000 UTF-16 units)"],
  ["x".repeat(500) + "  \n", "x".repeat(500), "500 plus trailing whitespace"],
  ["x".repeat(501), "too_long", "501 ASCII"],
  ["\u{1F600}".repeat(501), "too_long", "501 emoji"],
  ["", "empty", "empty string"],
  ["   ", "empty", "spaces"],
  ["\n\n", "empty", "newlines"],
  [" 　﻿ hola  ", "hola", "ideographic space and BOM trimmed"],
  ["a\nb", "a\nb", "inner newline"],
  ["a\tb", "control_character", "tab"],
  ["a\r\nb", "control_character", "carriage return"],
  ["a\u0000", "control_character", "NUL"],
  ["a\u0085", "control_character", "NEL (C1)"],
  ["a\u001b[31m", "control_character", "ANSI escape"],
  ["\uD800", "control_character", "lone high surrogate"],
  ["é", "é", "combining accent"],
];

const PROBLEMS = new Set(["control_character", "empty", "too_long"]);

describe("feedback message rule", () => {
  test.each(VECTORS)("vector %#: %j -> %j (%s)", (raw, expected) => {
    if (PROBLEMS.has(expected)) {
      expect(feedbackProblem(raw)).toBe(expected);
    } else {
      expect(feedbackProblem(raw)).toBeNull();
      expect(trimFeedback(raw)).toBe(expected);
    }
  });

  test("counts code points, not UTF-16 units, with no normalisation", () => {
    expect(FEEDBACK_MAX_CHARS).toBe(500);
    expect(countFeedbackChars("\u{1F600}".repeat(500))).toBe(500);
    expect("\u{1F600}".repeat(500).length).toBe(1000);
    expect(countFeedbackChars("é")).toBe(2);
    expect(countFeedbackChars("")).toBe(0);
  });

  test("a well-formed surrogate pair is fine; any unpaired surrogate is refused", () => {
    expect(feedbackProblem("😀")).toBeNull();
    expect(feedbackProblem("a\uDE00")).toBe("control_character");
    expect(feedbackProblem("\uD83Da")).toBe("control_character");
    expect(feedbackProblem("\uDE00\uD83D")).toBe("control_character");
  });

  test("controls are checked before trimming", () => {
    expect(feedbackProblem("hola\t")).toBe("control_character");
    expect(feedbackProblem("\rhola")).toBe("control_character");
    expect(feedbackProblem("a\u007F")).toBe("control_character");
    expect(feedbackProblem("a\u009F")).toBe("control_character");
    expect(feedbackProblem("\u000B")).toBe("control_character");
  });

  test("trims the ECMAScript whitespace set and keeps inner text", () => {
    for (const char of "        　﻿") {
      expect(trimFeedback(`${char}x${char}`)).toBe("x");
      expect(feedbackProblem(`${char}x${char}`)).toBeNull();
    }
    expect(trimFeedback("  a  b  ")).toBe("a  b");
    const family = "\u{1F468}‍\u{1F469}‍\u{1F467}";
    expect(feedbackProblem(family)).toBeNull();
    expect(trimFeedback(family)).toBe(family);
  });
});
