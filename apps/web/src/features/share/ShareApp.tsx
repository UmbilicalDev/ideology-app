import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  CheckIcon,
  FacebookIcon,
  InstagramIcon,
  LinkIcon,
  MailIcon,
  WhatsAppIcon,
  XIcon,
} from "../../ui/icons";
import { appShareLinks, SHARE_TEXT } from "./app-share-links";
import { CopySwap } from "./CopySwap";
import { useCopiedFlash } from "./useCopiedFlash";

const INTRO = "¿Te ha gustado IdeologiApp? Recomienda esta web a otras personas.";
const COPIED = "Enlace de IdeologiApp copiado.";
const COPIED_INSTAGRAM = "Enlace de IdeologiApp copiado. Ya puedes pegarlo en Instagram.";
const FALLBACK = "No se ha podido copiar el enlace automáticamente. Cópialo desde este campo:";
const FALLBACK_INSTAGRAM =
  "No se ha podido copiar el enlace automáticamente. Cópialo desde este campo y pégalo en " +
  "Instagram:";
const NEW_TAB_ID = "share-app-new-tab";

type Via = "copy" | "instagram";

type CopyState =
  | { readonly kind: "idle" }
  | { readonly kind: "copied"; readonly via: Via }
  | {
      readonly kind: "fallback";
      readonly via: Via;
      readonly url: string;
      /** Bumped on every failed copy so the field is focused and selected again. */
      readonly attempt: number;
    };

function statusText(copy: CopyState): string {
  switch (copy.kind) {
    case "idle":
      return "";
    case "copied":
      return copy.via === "instagram" ? COPIED_INSTAGRAM : COPIED;
    case "fallback":
      return copy.via === "instagram" ? FALLBACK_INSTAGRAM : FALLBACK;
  }
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { readonly name?: unknown }).name === "AbortError"
  );
}

/**
 * "Comparte IdeologiApp" (DESIGN.md "Share card"): six share targets that
 * share only the home URL (`appHomeUrl(location.origin)`), never a result.
 * The links are Voter-started navigations; nothing is loaded from another
 * origin and no request is made (CONSTRAINTS.md, Client-side Matching).
 */
export function ShareApp() {
  const [copy, setCopy] = useState<CopyState>({ kind: "idle" });
  const fieldRef = useRef<HTMLInputElement>(null);
  const [copied, flash] = useCopiedFlash();
  const fallbackAttempt = copy.kind === "fallback" ? copy.attempt : 0;
  const links = appShareLinks(window.location.origin);

  useEffect(() => {
    if (fallbackAttempt > 0) {
      fieldRef.current?.focus();
      fieldRef.current?.select();
    }
  }, [fallbackAttempt]);

  async function copyHome(via: Via) {
    const url = appShareLinks(window.location.origin).home;
    const clipboard: Clipboard | undefined = navigator.clipboard;
    if (typeof clipboard?.writeText === "function") {
      try {
        await clipboard.writeText(url);
        setCopy({ kind: "copied", via });
        if (via === "copy") flash();
        return;
      } catch {
        // Denied or failed: fall through to the field.
      }
    }
    setCopy((previous) => ({
      kind: "fallback",
      via,
      url,
      attempt: (previous.kind === "fallback" ? previous.attempt : 0) + 1,
    }));
  }

  async function shareInstagram() {
    const { home } = appShareLinks(window.location.origin);
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title: "IdeologiApp", text: SHARE_TEXT, url: home });
        setCopy({ kind: "idle" });
        return;
      } catch (error) {
        // The Voter cancelled the share sheet: say nothing, copy nothing.
        if (isAbort(error)) return;
      }
    }
    await copyHome("instagram");
  }

  return (
    <section className="share-app" aria-labelledby="share-app-title">
      <h3 id="share-app-title" className="share__title">
        Comparte IdeologiApp
      </h3>
      <p>{INTRO}</p>
      <ul className="share-targets">
        <li>
          <button
            type="button"
            className="share-target"
            aria-label="Copiar enlace de IdeologiApp"
            data-copied={copied}
            onClick={() => void copyHome("copy")}
          >
            <TargetContent
              icon={<CopySwap copied={copied} idle={<LinkIcon />} done={<CheckIcon />} />}
              caption={<CopySwap copied={copied} idle="Copiar enlace" done="¡Copiado!" />}
            />
          </button>
        </li>
        <li>
          <NewTabLink href={links.facebook} label="Compartir IdeologiApp en Facebook">
            <TargetContent icon={<FacebookIcon />} caption="Facebook" />
          </NewTabLink>
        </li>
        <li>
          <NewTabLink href={links.whatsapp} label="Compartir IdeologiApp en WhatsApp">
            <TargetContent icon={<WhatsAppIcon />} caption="WhatsApp" />
          </NewTabLink>
        </li>
        <li>
          <button
            type="button"
            className="share-target"
            aria-label="Compartir IdeologiApp en Instagram"
            onClick={() => void shareInstagram()}
          >
            <TargetContent icon={<InstagramIcon />} caption="Instagram" />
          </button>
        </li>
        <li>
          <NewTabLink href={links.x} label="Compartir IdeologiApp en X">
            <TargetContent icon={<XIcon />} caption="X" />
          </NewTabLink>
        </li>
        <li>
          <a
            className="share-target"
            href={links.email}
            aria-label="Compartir IdeologiApp por correo electrónico"
          >
            <TargetContent icon={<MailIcon />} caption="Correo" />
          </a>
        </li>
      </ul>
      {/* After a plain copy the tile itself says `¡Copiado!`, so the status
          is only announced; the Instagram hint and the fallback stay visible. */}
      <p
        role="status"
        className={copy.kind === "copied" && copy.via === "copy" ? "visually-hidden" : "share__status"}
      >
        {statusText(copy)}
      </p>
      {copy.kind === "fallback" ? (
        <>
          <label htmlFor="share-app-url">Enlace de IdeologiApp</label>
          <input
            id="share-app-url"
            ref={fieldRef}
            className="share__field"
            type="text"
            readOnly
            value={copy.url}
            onFocus={(event) => event.currentTarget.select()}
          />
        </>
      ) : null}
      <span id={NEW_TAB_ID} className="visually-hidden">
        (se abre en una pestaña nueva)
      </span>
    </section>
  );
}

function NewTabLink({
  href,
  label,
  children,
}: {
  readonly href: string;
  readonly label: string;
  readonly children: ReactNode;
}) {
  return (
    <a
      className="share-target"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      aria-describedby={NEW_TAB_ID}
    >
      {children}
    </a>
  );
}

function TargetContent({ icon, caption }: { readonly icon: ReactNode; readonly caption: ReactNode }) {
  return (
    <>
      <span className="share-target__icon">{icon}</span>
      <span className="share-target__label">{caption}</span>
    </>
  );
}
