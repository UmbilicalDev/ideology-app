// The signed-in admin page: header, filters, the message list and paging
// (DESIGN.md "Operator Admin Page"). Filters live in component state.
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import {
  AdminApiError,
  type AdminApi,
  type AdminFeedbackMessage,
  type FeedbackFilters,
  type ReviewedFilter,
} from "./admin-api";
import { FeedbackMessageCard } from "./FeedbackMessageCard";
import { shownCount } from "./format";

export const EMPTY_TEXT = "Todavía no hay mensajes.";
export const NO_MATCH_TEXT = "Ningún mensaje coincide con los filtros.";
export const DELETED_TEXT = "Mensaje borrado.";
export const LOAD_ERROR_TEXT = "No se pudieron cargar los mensajes.";
export const ACTION_ERROR_TEXT = "No se pudo completar la acción. Inténtalo de nuevo.";
export const RANGE_PROBLEM_TEXT = "La fecha «Hasta» no puede ser anterior a «Desde».";

interface Props {
  readonly api: AdminApi;
  readonly username: string;
  readonly onSessionExpired: () => void;
  readonly onNotConfigured: () => void;
  readonly onSignedOut: () => void;
}

const ALL: FeedbackFilters = { reviewed: "all" };

function hasFilters(filters: FeedbackFilters): boolean {
  return Boolean(filters.from) || Boolean(filters.to) || filters.reviewed !== "all";
}

type Load = "loading" | "ready" | "error";

export function FeedbackInbox({ api, username, onSessionExpired, onNotConfigured, onSignedOut }: Props) {
  const id = useId();
  const [filters, setFilters] = useState<FeedbackFilters>(ALL);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [reviewed, setReviewed] = useState<ReviewedFilter>("all");
  const [rangeProblem, setRangeProblem] = useState(false);
  const [messages, setMessages] = useState<readonly AdminFeedbackMessage[]>([]);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [load, setLoad] = useState<Load>("loading");
  const [loadingMore, setLoadingMore] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [pending, setPending] = useState<ReadonlySet<number>>(new Set());
  const [errors, setErrors] = useState<ReadonlyMap<number, string>>(new Map());
  const [signingOut, setSigningOut] = useState(false);
  const list = useRef<HTMLOListElement>(null);
  const statusLine = useRef<HTMLParagraphElement>(null);
  const focusAfterDelete = useRef<number | null>(null);
  const request = useRef(0);

  /** True when the error ended the session (the page leaves the inbox). */
  const handledSessionError = useCallback(
    (error: unknown): boolean => {
      if (error instanceof AdminApiError) {
        if (error.kind === "not_signed_in") {
          onSessionExpired();
          return true;
        }
        if (error.kind === "not_configured") {
          onNotConfigured();
          return true;
        }
      }
      return false;
    },
    [onSessionExpired, onNotConfigured],
  );

  const loadFirstPage = useCallback(
    (applied: FeedbackFilters) => {
      const current = ++request.current;
      setLoad("loading");
      setStatus(null);
      api.listFeedback(applied).then(
        (page) => {
          if (current !== request.current) return;
          setMessages(page.messages);
          setNextBeforeId(page.nextBeforeId);
          setErrors(new Map());
          setLoad("ready");
        },
        (error: unknown) => {
          if (current !== request.current) return;
          if (!handledSessionError(error)) setLoad("error");
        },
      );
    },
    [api, handledSessionError],
  );

  useEffect(() => {
    loadFirstPage(ALL);
  }, [loadFirstPage]);

  useLayoutEffect(() => {
    const index = focusAfterDelete.current;
    if (index === null) return;
    focusAfterDelete.current = null;
    const next = list.current?.children.item(index)?.querySelector("button");
    if (next instanceof HTMLButtonElement) {
      next.focus();
    } else {
      statusLine.current?.focus();
    }
  }, [messages]);

  function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (from !== "" && to !== "" && to < from) {
      setRangeProblem(true);
      return;
    }
    setRangeProblem(false);
    const applied: FeedbackFilters = {
      reviewed,
      ...(from === "" ? {} : { from }),
      ...(to === "" ? {} : { to }),
    };
    setFilters(applied);
    loadFirstPage(applied);
  }

  async function loadMore() {
    if (nextBeforeId === null || loadingMore) return;
    const current = request.current;
    setLoadingMore(true);
    try {
      const page = await api.listFeedback(filters, nextBeforeId);
      if (current !== request.current) return;
      setMessages((shown) => [...shown, ...page.messages]);
      setNextBeforeId(page.nextBeforeId);
      setStatus(null);
    } catch (error) {
      if (!handledSessionError(error)) setLoad("error");
    } finally {
      setLoadingMore(false);
    }
  }

  function setBusy(messageId: number, busy: boolean) {
    setPending((ids) => {
      const next = new Set(ids);
      if (busy) next.add(messageId);
      else next.delete(messageId);
      return next;
    });
  }

  function setError(messageId: number, text: string | null) {
    setErrors((map) => {
      const next = new Map(map);
      if (text === null) next.delete(messageId);
      else next.set(messageId, text);
      return next;
    });
  }

  async function toggleReviewed(message: AdminFeedbackMessage) {
    setBusy(message.id, true);
    setError(message.id, null);
    try {
      const updated =
        message.reviewedAt === null
          ? await api.markReviewed(message.id)
          : await api.unmarkReviewed(message.id);
      setMessages((shown) => shown.map((m) => (m.id === updated.id ? updated : m)));
      setStatus(null);
    } catch (error) {
      if (handledSessionError(error)) return;
      if (error instanceof AdminApiError && error.kind === "not_found") {
        removeMessage(message.id);
        return;
      }
      setError(message.id, ACTION_ERROR_TEXT);
    } finally {
      setBusy(message.id, false);
    }
  }

  function removeMessage(messageId: number) {
    setMessages((shown) => {
      const index = shown.findIndex((m) => m.id === messageId);
      focusAfterDelete.current = index === -1 ? null : index;
      return shown.filter((m) => m.id !== messageId);
    });
    setStatus(DELETED_TEXT);
  }

  async function deleteMessage(message: AdminFeedbackMessage) {
    setBusy(message.id, true);
    setError(message.id, null);
    try {
      await api.deleteFeedback(message.id);
      removeMessage(message.id);
    } catch (error) {
      if (handledSessionError(error)) return;
      if (error instanceof AdminApiError && error.kind === "not_found") {
        removeMessage(message.id);
        return;
      }
      setError(message.id, ACTION_ERROR_TEXT);
    } finally {
      setBusy(message.id, false);
    }
  }

  async function signOut() {
    setSigningOut(true);
    try {
      await api.signOut();
    } catch (error) {
      if (handledSessionError(error)) return;
    } finally {
      setSigningOut(false);
    }
    onSignedOut();
  }

  const statusText =
    load !== "ready" ? null : (status ?? (messages.length > 0 ? shownCount(messages.length) : null));

  return (
    <>
      <div className="admin-header">
        <p className="admin-header__user">Sesión iniciada como {username}</p>
        <button type="button" className="button-secondary" disabled={signingOut} onClick={signOut}>
          Cerrar sesión
        </button>
      </div>

      <form className="card admin-filters" onSubmit={submitFilters} noValidate>
        <fieldset>
          <legend>Filtrar</legend>
          <div className="admin-filters__fields">
            <div className="admin-field">
              <label htmlFor={`${id}-from`}>Desde (UTC)</label>
              <input
                id={`${id}-from`}
                type="date"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
              />
            </div>
            <div className="admin-field">
              <label htmlFor={`${id}-to`}>Hasta (UTC)</label>
              <input
                id={`${id}-to`}
                type="date"
                value={to}
                aria-invalid={rangeProblem || undefined}
                aria-describedby={rangeProblem ? `${id}-range` : undefined}
                onChange={(event) => setTo(event.target.value)}
              />
            </div>
            <div className="admin-field">
              <label htmlFor={`${id}-state`}>Estado</label>
              <select
                id={`${id}-state`}
                value={reviewed}
                onChange={(event) => setReviewed(event.target.value as ReviewedFilter)}
              >
                <option value="all">Todas</option>
                <option value="no">Sin revisar</option>
                <option value="yes">Revisadas</option>
              </select>
            </div>
          </div>
          {rangeProblem && (
            <p id={`${id}-range`} role="alert" className="admin__error">
              {RANGE_PROBLEM_TEXT}
            </p>
          )}
          <button type="submit" className="button-secondary">
            Filtrar
          </button>
        </fieldset>
      </form>

      <p ref={statusLine} role="status" tabIndex={-1} className="admin__status">
        {load === "loading" ? "Cargando…" : statusText}
      </p>

      {load === "error" && (
        <div className="admin-load-error">
          <p role="alert" className="admin__error">
            {LOAD_ERROR_TEXT}
          </p>
          <button type="button" className="button-primary" onClick={() => loadFirstPage(filters)}>
            Reintentar
          </button>
        </div>
      )}

      {load === "ready" && messages.length === 0 && (
        <p className="admin__empty">{hasFilters(filters) ? NO_MATCH_TEXT : EMPTY_TEXT}</p>
      )}

      {load === "ready" && messages.length > 0 && (
        <ol ref={list} className="admin-list" aria-label="Mensajes">
          {messages.map((message) => (
            <li key={message.id}>
              <FeedbackMessageCard
                message={message}
                pending={pending.has(message.id)}
                error={errors.get(message.id) ?? null}
                onToggleReviewed={() => void toggleReviewed(message)}
                onDelete={() => void deleteMessage(message)}
              />
            </li>
          ))}
        </ol>
      )}

      {load === "ready" && nextBeforeId !== null && (
        <button type="button" className="button-secondary admin-more" disabled={loadingMore} onClick={loadMore}>
          Cargar más
        </button>
      )}
    </>
  );
}
