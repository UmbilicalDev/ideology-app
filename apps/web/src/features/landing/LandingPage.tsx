import { Link } from "react-router";

import type { Election, PublicApi } from "@ideology-app/core";

import { METHODOLOGY_PATH, questionnairePath } from "../paths";
import { formatElectionDate } from "./format-date";
import { useElections, type ElectionsState } from "./useElections";

// Landing screen (DESIGN.md Core Screens 1). Lists exactly what the API
// returns (active Elections, API order); no party names or colours.
export function LandingPage({ api }: { readonly api: PublicApi }) {
  const { state, retry } = useElections(api);
  return (
    <main>
      <h1>Comparador de programas electorales</h1>
      <p>
        Responde a una serie de afirmaciones y descubre qué partidos se acercan más a tus
        respuestas, según sus programas electorales.
      </p>

      <section className="card" aria-labelledby="ai-disclosure-title">
        <h2 id="ai-disclosure-title">Contenido generado con IA</h2>
        <p>
          Las afirmaciones y las posiciones de los partidos las ha generado automáticamente una
          inteligencia artificial a partir de sus programas electorales, sin revisión humana, y
          pueden contener errores. Cada posición se apoya en una cita literal del programa que
          podrás consultar. Esta herramienta no es una recomendación de voto.
        </p>
      </section>

      <section aria-labelledby="elections-title">
        <h2 id="elections-title">Elecciones disponibles</h2>
        <ElectionsList state={state} retry={retry} />
      </section>

      <section aria-labelledby="methodology-title">
        <h2 id="methodology-title">Cómo funciona</h2>
        <p>
          Una inteligencia artificial lee los programas electorales de los partidos con
          representación en el Congreso, redacta afirmaciones neutrales y sitúa a cada partido ante
          cada afirmación con una cita literal como prueba.
        </p>
        <p>
          Antes de publicar los datos, unas comprobaciones automáticas verifican, entre otras
          cosas, que cada cita aparece en el programa. Tus respuestas se quedan en tu navegador: no
          se envían ni se guardan en ningún servidor.
        </p>
        <p>
          <Link className="text-link" to={METHODOLOGY_PATH}>
            Lee la metodología completa
          </Link>
        </p>
      </section>
    </main>
  );
}

function ElectionsList({
  state,
  retry,
}: {
  readonly state: ElectionsState;
  readonly retry: () => void;
}) {
  switch (state.kind) {
    case "loading":
      return <p role="status">Cargando elecciones…</p>;
    case "error":
      return (
        <div role="alert">
          <p>No se han podido cargar las elecciones. Comprueba tu conexión e inténtalo de nuevo.</p>
          <button type="button" className="button-primary" onClick={retry}>
            Reintentar
          </button>
        </div>
      );
    case "loaded":
      if (state.elections.length === 0) {
        return (
          <p>Ahora mismo no hay elecciones disponibles. Vuelve a consultarlo más adelante.</p>
        );
      }
      return (
        <ul className="election-list">
          {state.elections.map((election) => (
            <ElectionItem key={election.id} election={election} />
          ))}
        </ul>
      );
  }
}

function ElectionItem({ election }: { readonly election: Election }) {
  return (
    <li>
      <Link className="election-link" to={questionnairePath(election.id)}>
        <span className="election-link__name">{election.name}</span>{" "}
        <span className="election-link__date">{formatElectionDate(election.date)}</span>
      </Link>
    </li>
  );
}
