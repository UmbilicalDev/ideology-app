import { Link } from "react-router";

import type { Election, FeedbackApi, PublicApi } from "@ideology-app/core";

import { ArrowForwardIcon, InfoIcon, RobotIcon } from "../../ui/icons";
import { BrandTitle } from "../common/BrandTitle";
import { ExpandableCard } from "../common/ExpandableCard";
import { NoticeCard } from "../common/NoticeCard";
import { FeedbackButton } from "../feedback/FeedbackButton";
import { METHODOLOGY_PATH, questionnairePath } from "../paths";
import { formatElectionDate } from "./format-date";
import { useElections, type ElectionsState } from "./useElections";

const TRIAL_NOTICE =
  "Por ahora el cuestionario solo está disponible, a modo de prueba, para las elecciones " +
  "generales de 2023. Próximamente añadiremos las de 2026, cuando los partidos actualicen sus " +
  "programas electorales.";

// Landing screen (DESIGN.md Core Screens 1). Lists exactly what the API
// returns (active Elections, API order) after a fixed trial notice; no party
// names or colours. The methodology summary and the AI disclosure follow as
// collapsed cards.
export function LandingPage({ api }: { readonly api: PublicApi & FeedbackApi }) {
  const { state, retry } = useElections(api);
  return (
    <main>
      <header className="brand-header">
        <BrandTitle onBrand />
        <p className="brand-subtitle">Una forma sencilla de revisar los programas electorales</p>
      </header>
      <p>
        Responde a una serie de afirmaciones y descubre qué partidos se acercan más a tus
        respuestas, según sus programas electorales.
      </p>

      <section aria-labelledby="elections-title">
        <h2 id="elections-title">Elecciones disponibles</h2>
        <NoticeCard title="Versión de prueba" text={TRIAL_NOTICE} tone="warning" />
        <ElectionsList state={state} retry={retry} />
      </section>

      <ExpandableCard title="Cómo funciona" icon={<InfoIcon />}>
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
      </ExpandableCard>

      <ExpandableCard title="Contenido generado con IA" icon={<RobotIcon />}>
        <p>
          Las afirmaciones y las posiciones de los partidos las ha generado automáticamente una
          inteligencia artificial a partir de sus programas electorales, sin revisión humana, y
          pueden contener errores. Cada posición se apoya en una cita literal del programa que
          podrás consultar. Esta herramienta no es una recomendación de voto.
        </p>
      </ExpandableCard>

      <div className="feedback-entry">
        <FeedbackButton api={api} origin="landing" />
      </div>
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
        <span className="election-link__date">{formatElectionDate(election.date)}</span>{" "}
        <span className="election-link__cta">
          <span>Realizar cuestionario</span>
          <ArrowForwardIcon />
        </span>
      </Link>
    </li>
  );
}
