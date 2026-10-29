import {
  useLayoutEffect,
  useRef,
  type FormEvent,
  type KeyboardEvent,
  type RefObject,
} from "react";

import { FEEDBACK_MAX_CHARS } from "@ideology-app/core";

import { CheckCircleIcon, CloseIcon } from "../../ui/icons";
import { counterText, limitAnnouncement, prepareFeedback, problemText } from "./feedback-form";

export type FeedbackPhase = "editing" | "sending" | "sent";

const FOCUSABLE = "button:not([disabled]), textarea:not([disabled]), a[href]";

/**
 * The `Ayúdanos a mejorar` modal (DESIGN.md "Feedback dialog"): a native
 * `<dialog>` opened with `showModal()`, so the page behind it is inert.
 * Presentational: `FeedbackButton` owns the state and mounts this only while
 * the dialog is open. Every close goes through `dialog.close()` and then
 * `onClosed` (once; the `close` event is only a fallback).
 */
export function FeedbackDialog({
  phase,
  text,
  prepared,
  website,
  error,
  textareaRef,
  onTextChange,
  onWebsiteChange,
  onSubmit,
  onClosed,
}: {
  readonly phase: FeedbackPhase;
  readonly text: string;
  readonly prepared: string;
  readonly website: string;
  readonly error: string | null;
  readonly textareaRef: RefObject<HTMLTextAreaElement | null>;
  readonly onTextChange: (value: string) => void;
  readonly onWebsiteChange: (value: string) => void;
  readonly onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  readonly onClosed: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const doneRef = useRef<HTMLButtonElement>(null);
  // A backdrop click needs both the press and the release on the <dialog>
  // itself, so a selection dragged out of the text area never closes it.
  const pressedBackdrop = useRef(false);

  // StrictMode-safe: a second run finds the dialog already open.
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog !== null && !dialog.open) {
      dialog.showModal();
    }
    // Only on open (`FeedbackButton` never opens in `sent`); the phase effect
    // below focuses Cerrar after a send.
    textareaRef.current?.focus();
  }, []);

  // A layout effect, so it runs at commit: a passive one could run after a
  // quick close had already returned focus to the trigger.
  useLayoutEffect(() => {
    if (phase === "sent") {
      doneRef.current?.focus();
    }
  }, [phase]);

  // Browsers fire `close` as a queued task after `dialog.close()`, so a
  // click on the trigger could land in between; report the close now and
  // keep the event only for a close that did not come through here.
  const closed = useRef(false);
  function finish() {
    if (!closed.current) {
      closed.current = true;
      onClosed();
    }
  }

  function close() {
    dialogRef.current?.close();
    finish();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") {
      return;
    }
    const focusables = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE),
    ).filter((element) => element.tabIndex !== -1);
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (first === undefined || last === undefined) {
      return;
    }
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !focusables.includes(active as HTMLElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !focusables.includes(active as HTMLElement))) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="feedback-dialog"
      aria-labelledby="feedback-title"
      aria-describedby="feedback-subtitle"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClose={finish}
      onKeyDown={handleKeyDown}
      onPointerDown={(event) => {
        pressedBackdrop.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (pressedBackdrop.current && event.target === event.currentTarget) {
          close();
        }
        pressedBackdrop.current = false;
      }}
    >
      <div className="feedback-dialog__surface">
        <div className="feedback-dialog__header">
          <h2 id="feedback-title">Ayúdanos a mejorar</h2>
          <button type="button" className="icon-button" aria-label="Cerrar" onClick={close}>
            <CloseIcon />
          </button>
        </div>
        <p id="feedback-subtitle" className="feedback-dialog__subtitle">
          Dinos qué te ha parecido IdeologiApp
        </p>
        {phase === "sent" ? (
          <div className="feedback__thanks">
            <CheckCircleIcon />
            <p id="feedback-thanks" className="feedback__thanks-title">
              ¡Gracias por tu opinión!
            </p>
            <p>Nos ayuda a mejorar IdeologiApp.</p>
            <div className="feedback__actions">
              <button
                type="button"
                className="button-primary"
                aria-describedby="feedback-thanks"
                ref={doneRef}
                onClick={close}
              >
                Cerrar
              </button>
            </div>
          </div>
        ) : (
          <FeedbackForm
            sending={phase === "sending"}
            text={text}
            prepared={prepared}
            website={website}
            error={error}
            textareaRef={textareaRef}
            onTextChange={onTextChange}
            onWebsiteChange={onWebsiteChange}
            onSubmit={onSubmit}
          />
        )}
      </div>
    </dialog>
  );
}

function FeedbackForm({
  sending,
  text,
  prepared,
  website,
  error,
  textareaRef,
  onTextChange,
  onWebsiteChange,
  onSubmit,
}: {
  readonly sending: boolean;
  readonly text: string;
  readonly prepared: string;
  readonly website: string;
  readonly error: string | null;
  readonly textareaRef: RefObject<HTMLTextAreaElement | null>;
  readonly onTextChange: (value: string) => void;
  readonly onWebsiteChange: (value: string) => void;
  readonly onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const { count, problem } = prepareFeedback(prepared);
  const problemLine = problemText(problem);
  const describedBy =
    problemLine === null ? "feedback-hint feedback-limit" : "feedback-hint feedback-limit feedback-problem";
  const over = count > FEEDBACK_MAX_CHARS;
  return (
    <form noValidate onSubmit={onSubmit}>
      <label className="feedback__label" htmlFor="feedback-message">
        Tu opinión
      </label>
      <textarea
        id="feedback-message"
        className="feedback__field"
        rows={6}
        value={text}
        readOnly={sending}
        aria-describedby={describedBy}
        ref={textareaRef}
        onChange={(event) => onTextChange(event.target.value)}
      />
      <p className={over ? "feedback__counter feedback__counter--over" : "feedback__counter"} aria-hidden="true">
        {counterText(count)}
      </p>
      <span id="feedback-limit" className="visually-hidden">
        Máximo {FEEDBACK_MAX_CHARS} caracteres.
      </span>
      <p id="feedback-hint" className="feedback__hint">
        Solo se guarda el texto, la pantalla desde la que lo envías y la fecha. No escribas datos
        personales.
      </p>
      <p role="status" className="visually-hidden">
        {limitAnnouncement(count)}
      </p>
      {problemLine === null ? null : (
        <p id="feedback-problem" className="feedback__problem">
          {problemLine}
        </p>
      )}
      <div className="visually-hidden" aria-hidden="true">
        <label htmlFor="feedback-website">Sitio web (déjalo vacío)</label>
        <input
          id="feedback-website"
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(event) => onWebsiteChange(event.target.value)}
        />
      </div>
      {error === null ? null : (
        <p role="alert" className="feedback__alert">
          {error}
        </p>
      )}
      {sending ? (
        <p role="status" className="feedback__sending">
          Enviando tu opinión…
        </p>
      ) : null}
      <div className="feedback__actions">
        <button type="submit" className="button-primary" disabled={problem !== null || sending}>
          Enviar
        </button>
      </div>
    </form>
  );
}
