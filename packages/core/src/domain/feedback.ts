// The Voter feedback message rule (feedback-api, Decision 1). Pure: no React,
// DOM, storage or network. The server holds the same rule in
// `src/ideology_app/feedback/message.py`; both are kept equal by the shared
// vectors in `test/domain/feedback.test.ts` and `tests/test_feedback_message.py`.
//
// Order: refused characters on the raw text (C0/C1 controls other than "\n",
// and unpaired surrogates), then `String.prototype.trim`, then a count in
// Unicode code points (an emoji counts 1; no normalisation, no graphemes).
// A dialog must count with `countFeedbackChars`, never `maxLength` or
// `.length`, which count UTF-16 units.

export const FEEDBACK_MAX_CHARS = 500;

export type FeedbackOrigin = "landing" | "results";

export type FeedbackProblem = "control_character" | "empty" | "too_long";

// C0 except "\n" (U+000A), DEL and C1.
const CONTROL_CHARACTER = /[\u0000-\u0009\u000B-\u001F\u007F-\u009F]/;
// A high surrogate not followed by a low one, or a low one not preceded by a
// high one (ES2022 lib: no `String.prototype.isWellFormed`).
const UNPAIRED_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** The text the server stores: `text.trim()`. */
export function trimFeedback(text: string): string {
  return text.trim();
}

/** Unicode code points, as the server counts them. */
export function countFeedbackChars(text: string): number {
  return Array.from(text).length;
}

/** The first problem of the raw text, or `null` when the server accepts it. */
export function feedbackProblem(text: string): FeedbackProblem | null {
  if (CONTROL_CHARACTER.test(text) || UNPAIRED_SURROGATE.test(text)) {
    return "control_character";
  }
  const count = countFeedbackChars(trimFeedback(text));
  if (count === 0) {
    return "empty";
  }
  if (count > FEEDBACK_MAX_CHARS) {
    return "too_long";
  }
  return null;
}
