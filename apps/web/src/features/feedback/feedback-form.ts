// Pure helpers for the feedback dialog (feedback-dialog spec, Decisions 5-6).
// The count and the rule come from `packages/core` (`countFeedbackChars`,
// `trimFeedback`, `feedbackProblem`): never `maxLength` or `.length`, which
// count UTF-16 units.
import {
  FEEDBACK_MAX_CHARS,
  PublicApiError,
  countFeedbackChars,
  feedbackProblem,
  trimFeedback,
  type FeedbackProblem,
} from "@ideology-app/core";

export interface PreparedFeedback {
  /** The text with tabs replaced by spaces; nothing else is changed. */
  readonly prepared: string;
  /** What the server will store: `trimFeedback(prepared)`. */
  readonly message: string;
  /** Code points of `message`, as the server counts them. */
  readonly count: number;
  readonly problem: FeedbackProblem | null;
}

/** Pasted tabs become spaces (the server refuses `\t`); then the shared rule. */
export function prepareFeedback(text: string): PreparedFeedback {
  const prepared = text.replace(/\t/g, " ");
  const message = trimFeedback(prepared);
  return {
    prepared,
    message,
    count: countFeedbackChars(message),
    problem: feedbackProblem(prepared),
  };
}

export function counterText(count: number): string {
  return `${count}/${FEEDBACK_MAX_CHARS}`;
}

/**
 * The polite announcement for the band `count` falls in. It changes only when
 * the band changes, so a screen reader hears each band once.
 */
export function limitAnnouncement(count: number): string {
  const remaining = FEEDBACK_MAX_CHARS - count;
  if (remaining > 50) {
    return "";
  }
  if (remaining > 25) {
    return "Quedan 50 caracteres o menos.";
  }
  if (remaining > 10) {
    return "Quedan 25 caracteres o menos.";
  }
  if (remaining > 0) {
    return "Quedan 10 caracteres o menos.";
  }
  if (remaining === 0) {
    return `Has llegado al límite de ${FEEDBACK_MAX_CHARS} caracteres.`;
  }
  return `Has superado el límite de ${FEEDBACK_MAX_CHARS} caracteres.`;
}

/** The visible problem line, or `null` (an empty text only disables Enviar). */
export function problemText(problem: FeedbackProblem | null): string | null {
  switch (problem) {
    case "too_long":
      return `Has superado el límite de ${FEEDBACK_MAX_CHARS} caracteres. Borra texto para poder enviar.`;
    case "control_character":
      return (
        "El texto tiene caracteres invisibles que no se pueden enviar. Prueba a escribirlo en " +
        "lugar de pegarlo."
      );
    case "empty":
    case null:
      return null;
  }
}

/** The retry message for a failed send. */
export function errorText(error: unknown): string {
  if (error instanceof PublicApiError) {
    if (error.kind === "network") {
      return "No se ha podido enviar tu opinión. Comprueba tu conexión e inténtalo de nuevo.";
    }
    if (error.kind === "http") {
      if (error.status === 429) {
        return (
          "Se han enviado muchas opiniones en poco tiempo. Espera unos minutos e inténtalo de " +
          "nuevo."
        );
      }
      if (error.status === 413 || error.status === 415 || error.status === 422) {
        return "El servidor no ha aceptado el mensaje. Revisa el texto e inténtalo de nuevo.";
      }
    }
  }
  return "No se ha podido enviar tu opinión. Inténtalo de nuevo más tarde.";
}
