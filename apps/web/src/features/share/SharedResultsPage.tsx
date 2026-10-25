import { useEffect, useRef } from "react";
import { Link, useLocation } from "react-router";

import { summarize, type OpenShareLinkResult, type PublicApi } from "@ideology-app/core";

import { HomeButton } from "../common/HomeButton";
import { NoticeCard } from "../common/NoticeCard";
import { METHODOLOGY_PATH, questionnairePath } from "../paths";
import { ResultsBreakdown } from "../results/ResultsBreakdown";
import { ResultsRanking } from "../results/ResultsRanking";
import { useSharedResult } from "./useSharedResult";

export const SHARED_RESULTS_TITLE = "Resultado compartido · Comparador de programas electorales";

const MISSING = "Este enlace no contiene ningún resultado. Comprueba que lo has copiado entero.";
const INVALID =
  "Este enlace no es válido o está incompleto. Comprueba que lo has copiado entero o pide que " +
  "te lo envíen de nuevo.";
const UNSUPPORTED =
  "Este enlace se creó con una versión más reciente de esta web. Recarga la página para abrirlo.";
const NOT_FOUND = "No encontramos el cuestionario de este enlace. Puede que ya no esté disponible.";
const ERROR = "No se ha podido cargar el resultado. Comprueba tu conexión e inténtalo de nuevo.";

const SUPERSEDED =
  "Este resultado se calculó con una versión anterior del cuestionario de estas elecciones y se " +
  "muestra tal como era. El cuestionario actual puede tener otras afirmaciones y otras posiciones.";
const RESULTS_INTRO =
  "Afinidad entre las respuestas de este enlace y el programa de cada partido, de mayor a menor.";
const NO_SCORES =
  "Las respuestas de este enlace no permiten calcular la afinidad: ninguna afirmación respondida " +
  "tiene la posición de algún partido.";
const DISCLAIMER =
  "Esto no es una recomendación de voto: solo compara estas respuestas con lo que dicen los " +
  "programas, según una inteligencia artificial que puede equivocarse.";
const NOTE =
  "Este resultado se calcula en tu navegador a partir del propio enlace: las respuestas van tras " +
  "el símbolo «#» y no se envían a ningún servidor. Para volver a verlo, guarda el enlace.";

/**
 * `/resultados#<payload>` (DESIGN.md Core Screens 5): the read-only result of
 * a Share Link. The fragment is read once per mount from the router location
 * and never rewritten, stored, logged or sent: only `openShareLink` decodes
 * it, and its requests carry ids only.
 */
export function SharedResultsPage({ api }: { readonly api: PublicApi }) {
  const { hash } = useLocation();
  const fragment = hash.startsWith("#") ? hash.slice(1) : hash;
  return <SharedResultLoader key={hash} api={api} fragment={fragment} />;
}

function SharedResultLoader({ api, fragment }: { readonly api: PublicApi; readonly fragment: string }) {
  const { state, retry } = useSharedResult(api, fragment);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = SHARED_RESULTS_TITLE;
    headingRef.current?.focus();
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <main>
      <h1 ref={headingRef} tabIndex={-1}>
        Resultado compartido
      </h1>
      {(() => {
        switch (state.kind) {
          case "loading":
            return <p role="status">Cargando resultado…</p>;
          case "missing":
            return <Message text={MISSING} />;
          case "invalid":
            return <Message text={state.reason === "unsupported_version" ? UNSUPPORTED : INVALID} />;
          case "not_found":
            return <Message text={NOT_FOUND} />;
          case "error":
            return (
              <>
                <div role="alert">
                  <p>{ERROR}</p>
                  <button type="button" className="button-primary" onClick={retry}>
                    Reintentar
                  </button>
                </div>
                <HomeButton />
              </>
            );
          case "ready":
            return <SharedResult result={state} />;
        }
      })()}
    </main>
  );
}

function Message({ text }: { readonly text: string }) {
  return (
    <>
      <p>{text}</p>
      <HomeButton />
    </>
  );
}

function SharedResult({ result }: { readonly result: Extract<OpenShareLinkResult, { kind: "ready" }> }) {
  const { election, state, results, versionStatus, questionnaireAvailable } = result;
  const { answered, skipped, important, total } = summarize(state);
  const superseded = versionStatus === "superseded";
  return (
    <>
      <p className="questionnaire__election">{election.name}</p>
      {superseded ? (
        <section className="card shared-notice" aria-labelledby="superseded-title">
          <h2 id="superseded-title">Hay un cuestionario más reciente</h2>
          <p>{SUPERSEDED}</p>
          {questionnaireAvailable ? (
            <p>
              <Link className="button-primary" to={questionnairePath(election.id)}>
                Hacer el cuestionario actual
              </Link>
            </p>
          ) : null}
        </section>
      ) : null}
      <h2 id="results-title">Afinidad con cada partido</h2>
      <p>{`Se respondieron ${answered} de ${total} afirmaciones y se saltaron ${skipped}.`}</p>
      <p>{importantSentence(important)}</p>
      {results.hasScores ? (
        <>
          <p>{RESULTS_INTRO}</p>
          <ResultsRanking ranking={results.ranking} />
        </>
      ) : (
        <p>{NO_SCORES}</p>
      )}
      <NoticeCard text={DISCLAIMER} />
      <p>
        <Link className="text-link" to={METHODOLOGY_PATH}>
          Cómo se calcula la afinidad
        </Link>
      </p>
      {!superseded && questionnaireAvailable ? (
        <p>
          <Link className="button-primary" to={questionnairePath(election.id)}>
            Haz tú el cuestionario
          </Link>
        </p>
      ) : null}
      <ResultsBreakdown rows={results.breakdown} answerOwner="link" />
      <p className="questionnaire__note">{NOTE}</p>
      <HomeButton />
    </>
  );
}

function importantSentence(count: number): string {
  if (count === 0) {
    return "No se marcó ninguna afirmación como importante.";
  }
  if (count === 1) {
    return "Se marcó 1 afirmación como importante.";
  }
  return `Se marcaron ${count} afirmaciones como importantes.`;
}
