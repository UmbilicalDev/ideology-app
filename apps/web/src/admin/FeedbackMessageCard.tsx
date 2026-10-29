// One feedback message on the admin page, with its actions and the inline
// delete confirmation (DESIGN.md "Operator Admin Page").
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { AdminFeedbackMessage } from "./admin-api";
import { formatUtcDateTime, originLabel } from "./format";

export const CONFIRM_TEXT = "¿Borrar este mensaje para siempre? No se puede deshacer.";

interface Props {
  readonly message: AdminFeedbackMessage;
  readonly pending: boolean;
  readonly error: string | null;
  readonly onToggleReviewed: () => void;
  readonly onDelete: () => void;
}

export function FeedbackMessageCard({ message, pending, error, onToggleReviewed, onDelete }: Props) {
  const [confirming, setConfirming] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  // Focus moves only after the user opened or closed the confirmation.
  const moveFocus = useRef<"cancel" | "delete" | null>(null);

  useEffect(() => {
    if (moveFocus.current === "cancel") cancelButton.current?.focus();
    if (moveFocus.current === "delete") deleteButton.current?.focus();
    moveFocus.current = null;
  }, [confirming]);

  function open() {
    moveFocus.current = "cancel";
    setConfirming(true);
  }

  function close() {
    moveFocus.current = "delete";
    setConfirming(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  const reviewed = message.reviewedAt !== null;

  return (
    <article className="card admin-message" aria-label={`Mensaje #${message.id}`}>
      <p className="admin-message__meta">
        <span>
          #{message.id} · {formatUtcDateTime(message.createdAt)} · {originLabel(message.origin)}
        </span>
        {reviewed && <span className="important-mark admin-message__chip">Revisado</span>}
      </p>
      <p className="admin-message__text">{message.message}</p>
      {error !== null && (
        <p role="alert" className="admin__error">
          {error}
        </p>
      )}
      {confirming ? (
        <div className="admin-message__confirm" role="group" aria-label="Confirmar borrado" onKeyDown={onKeyDown}>
          <p>{CONFIRM_TEXT}</p>
          <div className="admin-message__actions">
            <button type="button" className="button-primary" disabled={pending} onClick={onDelete}>
              Borrar definitivamente
            </button>
            <button ref={cancelButton} type="button" className="button-secondary" onClick={close}>
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        <div className="admin-message__actions">
          <button
            type="button"
            className="button-secondary"
            disabled={pending}
            aria-busy={pending || undefined}
            onClick={onToggleReviewed}
          >
            {reviewed ? "Marcar como no revisado" : "Marcar como revisado"}
          </button>
          <button
            ref={deleteButton}
            type="button"
            className="button-secondary"
            disabled={pending}
            onClick={open}
          >
            Borrar
          </button>
        </div>
      )}
    </article>
  );
}
