import { useEffect, useRef, useState } from "react";

import { encodeShareLink, type QuestionnaireState } from "@ideology-app/core";

import { CheckIcon, InfoIcon, LinkIcon, ShareIcon } from "../../ui/icons";
import { sharedResultsUrl } from "../paths";
import { CopySwap } from "./CopySwap";
import { useCopiedFlash } from "./useCopiedFlash";

const COPIED = "Enlace copiado.";
const FALLBACK = "No se ha podido copiar el enlace automáticamente. Cópialo desde este campo:";
const NOTE =
  "No se guarda nada en ningún servidor: tus respuestas van dentro del propio enlace, tras el " +
  "símbolo «#», y el navegador no envía esa parte de la dirección. Cualquiera que tenga el " +
  "enlace podrá ver tus respuestas.";

type CopyState = { readonly kind: "idle" } | { readonly kind: "copied" } | {
  readonly kind: "fallback";
  readonly url: string;
  /** Bumped on every failed copy so the field is focused and selected again. */
  readonly attempt: number;
};

/**
 * The end screen's Share Link (DESIGN.md "Share button"). The link is built
 * in the browser on click and only goes to the clipboard or, when that is
 * missing or denied, into a read-only field. It is never written to the
 * current URL, history or storage, and no request is made
 * (CONSTRAINTS.md, Client-side Matching).
 */
export function ShareResults({
  datasetVersionId,
  state,
}: {
  readonly datasetVersionId: number;
  readonly state: QuestionnaireState;
}) {
  const [copy, setCopy] = useState<CopyState>({ kind: "idle" });
  const [noteOpen, setNoteOpen] = useState(false);
  const [copied, flash] = useCopiedFlash();
  const fieldRef = useRef<HTMLInputElement>(null);
  const fallbackAttempt = copy.kind === "fallback" ? copy.attempt : 0;

  useEffect(() => {
    if (fallbackAttempt > 0) {
      fieldRef.current?.focus();
      fieldRef.current?.select();
    }
  }, [fallbackAttempt]);

  async function handleCopy() {
    const url = sharedResultsUrl(window.location.origin, encodeShareLink(state, datasetVersionId));
    const clipboard: Clipboard | undefined = navigator.clipboard;
    if (typeof clipboard?.writeText === "function") {
      try {
        await clipboard.writeText(url);
        setCopy({ kind: "copied" });
        flash();
        return;
      } catch {
        // Denied or failed: fall through to the field.
      }
    }
    setCopy((previous) => ({
      kind: "fallback",
      url,
      attempt: (previous.kind === "fallback" ? previous.attempt : 0) + 1,
    }));
  }

  return (
    <section className="share" aria-labelledby="share-title">
      <div className="share__header">
        <h3 id="share-title" className="share__title">
          <ShareIcon />
          <span>Comparte tu resultado</span>
        </h3>
        <button
          type="button"
          className="icon-button share__info"
          aria-label="Privacidad del enlace"
          aria-expanded={noteOpen}
          aria-controls="share-note"
          onClick={() => setNoteOpen((open) => !open)}
        >
          <InfoIcon />
        </button>
      </div>
      <p id="share-note" className="questionnaire__note share__note" hidden={!noteOpen}>
        {NOTE}
      </p>
      <p>Copia un enlace que lleva tus respuestas para compartir este resultado.</p>
      <button
        type="button"
        className="button-tonal copy-button"
        data-copied={copied}
        onClick={() => void handleCopy()}
      >
        <CopySwap
          copied={copied}
          idle={
            <>
              <LinkIcon />
              <span>Copiar enlace</span>
            </>
          }
          done={
            <>
              <CheckIcon />
              <span>¡Copiado!</span>
            </>
          }
        />
      </button>
      {/* The button itself shows `¡Copiado!`; the status still tells screen
          readers, and shows the fallback when the copy fails. */}
      <p role="status" className={copy.kind === "fallback" ? "share__status" : "visually-hidden"}>
        {copy.kind === "copied" ? COPIED : copy.kind === "fallback" ? FALLBACK : ""}
      </p>
      {copy.kind === "fallback" ? (
        <>
          <label htmlFor="share-url">Enlace para compartir</label>
          <input
            id="share-url"
            ref={fieldRef}
            className="share__field"
            type="text"
            readOnly
            value={copy.url}
            onFocus={(event) => event.currentTarget.select()}
          />
        </>
      ) : null}
    </section>
  );
}
