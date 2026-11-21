import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

const TITLE = "¿Repetir el cuestionario?";
const TEXT =
  "Se borrarán tus respuestas y el resultado. Copia antes el enlace si quieres guardarlo.";

/**
 * `Repetir cuestionario` and its confirmation (DESIGN.md "Restart
 * confirmation"). It receives only `onConfirm`, never Questionnaire state.
 * Cancelling (Cancelar, Escape, a backdrop click) changes nothing and returns
 * focus to the button; `Sí, repetir` calls `onConfirm`, whose move puts focus
 * on Statement 1.
 */
export function RestartButton({ onConfirm }: { readonly onConfirm: () => void }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  function handleClosed(confirmed: boolean) {
    setOpen(false);
    if (confirmed) {
      onConfirm();
    } else {
      triggerRef.current?.focus();
    }
  }

  return (
    <>
      <button
        type="button"
        className="button-primary"
        aria-haspopup="dialog"
        ref={triggerRef}
        onClick={() => setOpen(true)}
      >
        Repetir cuestionario
      </button>
      {open ? <RestartDialog onClosed={handleClosed} /> : null}
    </>
  );
}

/**
 * A native `<dialog>` opened with `showModal()`, so the page behind it is
 * inert. Every close goes through `dialog.close()` and then `onClosed`
 * (once; the `close` event is only a fallback), as in `FeedbackDialog`.
 */
function RestartDialog({ onClosed }: { readonly onClosed: (confirmed: boolean) => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const pressedBackdrop = useRef(false);
  const closed = useRef(false);

  // StrictMode-safe: a second run finds the dialog already open.
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog !== null && !dialog.open) {
      dialog.showModal();
    }
    // The safe choice first.
    cancelRef.current?.focus();
  }, []);

  // Set before `dialog.close()`, so a `close` event fired during it (as some
  // implementations do) reports the right choice.
  const confirmed = useRef(false);

  function finish() {
    if (!closed.current) {
      closed.current = true;
      onClosed(confirmed.current);
    }
  }

  function close(confirm: boolean) {
    confirmed.current = confirm;
    dialogRef.current?.close();
    finish();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") {
      return;
    }
    const first = cancelRef.current;
    const last = confirmRef.current;
    if (first === null || last === null) {
      return;
    }
    // Two buttons: Tab and Shift+Tab both go to the other one, so focus
    // never leaves the dialog.
    event.preventDefault();
    (document.activeElement === first ? last : first).focus();
  }

  return (
    <dialog
      ref={dialogRef}
      className="confirm-dialog"
      aria-labelledby="restart-title"
      aria-describedby="restart-text"
      onCancel={(event) => {
        event.preventDefault();
        close(false);
      }}
      onClose={finish}
      onKeyDown={handleKeyDown}
      onPointerDown={(event) => {
        pressedBackdrop.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (pressedBackdrop.current && event.target === event.currentTarget) {
          close(false);
        }
        pressedBackdrop.current = false;
      }}
    >
      <div className="confirm-dialog__surface">
        <h2 id="restart-title">{TITLE}</h2>
        <p id="restart-text" className="confirm-dialog__text">
          {TEXT}
        </p>
        <div className="confirm-dialog__actions">
          <button type="button" className="button-secondary" ref={cancelRef} onClick={() => close(false)}>
            Cancelar
          </button>
          <button type="button" className="button-primary" ref={confirmRef} onClick={() => close(true)}>
            Sí, repetir
          </button>
        </div>
      </div>
    </dialog>
  );
}
