// Port: sending anonymous Voter feedback (`POST /api/v1/feedback`). Separate
// from `PublicApi`, which stays read-only. Implemented by
// `infrastructure/http/public-api-client.ts`; components never call fetch.
import type { FeedbackOrigin } from "../domain/feedback";

export interface FeedbackInput {
  /** Sent as given: the server trims and checks it (`feedbackProblem` mirrors the rule). */
  readonly message: string;
  /** The screen the message is sent from. */
  readonly origin: FeedbackOrigin;
  /** Honeypot: sent only when non-empty; a real Voter never fills it. */
  readonly website?: string;
}

export interface FeedbackApi {
  /** Resolves once the server answered 2xx; never carries Answers. */
  sendFeedback(feedback: FeedbackInput): Promise<void>;
}
