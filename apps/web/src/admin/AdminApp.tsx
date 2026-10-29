// The Operator admin page (feedback-admin; DESIGN.md "Operator Admin Page"):
// a small state machine, checking -> not_configured | signed_out | signed_in.
// No router: one page at /admin.
import { useEffect, useRef, useState } from "react";

import { NoticeCard } from "../features/common/NoticeCard";
import { AdminApiError, type AdminApi } from "./admin-api";
import { FeedbackInbox } from "./FeedbackInbox";
import { SignInForm } from "./SignInForm";

export const NOT_CONFIGURED_TEXT =
  "No hay ninguna cuenta de Operador configurada. Define ADMIN_USERS en el servidor; " +
  "el README explica cómo (ideology admin hash-password).";
export const SESSION_EXPIRED_TEXT = "Tu sesión ha caducado. Vuelve a iniciar sesión.";

type State =
  | { readonly kind: "checking" }
  | { readonly kind: "not_configured" }
  | { readonly kind: "signed_out"; readonly notice?: string }
  | { readonly kind: "signed_in"; readonly username: string };

export function AdminApp({ api }: { readonly api: AdminApi }) {
  const [state, setState] = useState<State>({ kind: "checking" });
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus();
  }, []);

  useEffect(() => {
    let active = true;
    api.getSession().then(
      (session) => {
        if (active) setState({ kind: "signed_in", username: session.username });
      },
      (error: unknown) => {
        if (!active) return;
        if (error instanceof AdminApiError && error.kind === "not_configured") {
          setState({ kind: "not_configured" });
        } else {
          setState({ kind: "signed_out" });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [api]);

  return (
    <main className="admin">
      <h1 ref={heading} tabIndex={-1}>
        Administración
      </h1>
      {state.kind === "checking" && (
        <p role="status" className="admin__status">
          Cargando…
        </p>
      )}
      {state.kind === "not_configured" && <NoticeCard text={NOT_CONFIGURED_TEXT} />}
      {state.kind === "signed_out" && (
        <SignInForm
          api={api}
          notice={state.notice}
          onSignedIn={(username) => setState({ kind: "signed_in", username })}
          onNotConfigured={() => setState({ kind: "not_configured" })}
        />
      )}
      {state.kind === "signed_in" && (
        <FeedbackInbox
          api={api}
          username={state.username}
          onSessionExpired={() => setState({ kind: "signed_out", notice: SESSION_EXPIRED_TEXT })}
          onNotConfigured={() => setState({ kind: "not_configured" })}
          onSignedOut={() => setState({ kind: "signed_out" })}
        />
      )}
    </main>
  );
}
