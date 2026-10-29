// Operator sign-in card (DESIGN.md "Operator Admin Page", Sign-in).
import { useId, useRef, useState, type FormEvent } from "react";

import { AdminApiError, type AdminApi } from "./admin-api";
import { retryMinutes } from "./format";

export const INVALID_CREDENTIALS_TEXT = "Usuario o contraseña incorrectos.";
export const NETWORK_TEXT = "No se pudo conectar. Inténtalo de nuevo.";

export function rateLimitedText(seconds: number | undefined): string {
  const minutes = retryMinutes(seconds);
  return `Demasiados intentos. Vuelve a intentarlo en ${minutes} ${minutes === 1 ? "minuto" : "minutos"}.`;
}

interface Props {
  readonly api: AdminApi;
  readonly notice: string | undefined;
  readonly onSignedIn: (username: string) => void;
  readonly onNotConfigured: () => void;
}

export function SignInForm({ api, notice, onSignedIn, onNotConfigured }: Props) {
  const id = useId();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passwordField = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const session = await api.signIn(username.trim(), password);
      onSignedIn(session.username);
      return;
    } catch (caught) {
      const kind = caught instanceof AdminApiError ? caught.kind : "network";
      if (kind === "not_configured") {
        onNotConfigured();
        return;
      }
      if (kind === "invalid_credentials") {
        setError(INVALID_CREDENTIALS_TEXT);
      } else if (kind === "rate_limited") {
        setError(
          rateLimitedText(caught instanceof AdminApiError ? caught.retryAfterSeconds : undefined),
        );
      } else {
        setError(NETWORK_TEXT);
      }
      setPassword("");
      setPending(false);
      passwordField.current?.focus();
    }
  }

  return (
    <section className="card admin-sign-in" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>Iniciar sesión</h2>
      {notice !== undefined && <p className="admin__notice">{notice}</p>}
      <form onSubmit={submit} noValidate>
        <div className="admin-field">
          <label htmlFor={`${id}-username`}>Usuario</label>
          <input
            id={`${id}-username`}
            name="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>
        <div className="admin-field">
          <label htmlFor={`${id}-password`}>Contraseña</label>
          <input
            ref={passwordField}
            id={`${id}-password`}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {error !== null && (
          <p role="alert" className="admin__error">
            {error}
          </p>
        )}
        <button type="submit" className="button-primary" disabled={pending}>
          Entrar
        </button>
      </form>
    </section>
  );
}
