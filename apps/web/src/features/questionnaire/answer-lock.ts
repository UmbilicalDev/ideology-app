/**
 * The double-tap guard of the Questionnaire (spec questionnaire-quick-answer,
 * Decision 7): after every move (an answer, `Anterior`, `Repetir`), the
 * answer buttons and `Anterior` ignore activations for `ms` milliseconds,
 * longer than the 0.22 s step transition. Mutable so tests can set it:
 * `src/test/setup.ts` sets 0 before each test.
 */
export const ANSWER_LOCK: { ms: number } = { ms: 300 };
