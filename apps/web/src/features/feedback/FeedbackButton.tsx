import { useRef, useState, type FormEvent } from "react";

import type { FeedbackApi, FeedbackOrigin } from "@ideology-app/core";

import { FeedbackIcon } from "../../ui/icons";
import { FeedbackDialog, type FeedbackPhase } from "./FeedbackDialog";
import { errorText, prepareFeedback } from "./feedback-form";

/**
 * `Danos tu opinión` and its dialog (DESIGN.md "Feedback button"). It gets
 * only the feedback port and the origin screen: never Questionnaire state.
 * The draft lives only in this component's state (no URL, no storage), so it
 * survives closing and reopening while the page stays mounted.
 */
export function FeedbackButton({
  api,
  origin,
}: {
  readonly api: FeedbackApi;
  readonly origin: FeedbackOrigin;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [website, setWebsite] = useState("");
  const [phase, setPhase] = useState<FeedbackPhase>("editing");
  const [error, setError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sending = useRef(false);

  const { prepared, message, problem } = prepareFeedback(text);

  function openDialog() {
    if (phase === "sent") {
      setPhase("editing");
      setText("");
      setWebsite("");
      setError(null);
    }
    setOpen(true);
  }

  // Every close goes through `dialog.close()`; this runs on its `close` event.
  function handleClosed() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function changeText(value: string) {
    setText(value);
    setError(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending.current || problem !== null) {
      return;
    }
    sending.current = true;
    setPhase("sending");
    setError(null);
    // Enviar becomes disabled; keep focus on the (read-only) text area.
    textareaRef.current?.focus();
    try {
      await api.sendFeedback({ message, origin, website });
      setText("");
      setWebsite("");
      setPhase("sent");
    } catch (failure) {
      setError(errorText(failure));
      setPhase("editing");
      textareaRef.current?.focus();
    } finally {
      sending.current = false;
    }
  }

  return (
    <>
      <button
        type="button"
        className="button-secondary"
        aria-haspopup="dialog"
        ref={triggerRef}
        onClick={openDialog}
      >
        <FeedbackIcon />
        <span>Danos tu opinión</span>
      </button>
      {open ? (
        <FeedbackDialog
          phase={phase}
          text={text}
          prepared={prepared}
          website={website}
          error={error}
          textareaRef={textareaRef}
          onTextChange={changeText}
          onWebsiteChange={setWebsite}
          onSubmit={(event) => void submit(event)}
          onClosed={handleClosed}
        />
      ) : null}
    </>
  );
}
