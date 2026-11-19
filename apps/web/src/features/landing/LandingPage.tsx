import { useEffect, useRef } from "react";
import { Link } from "react-router";

import type { Election, PublicApi } from "@ideology-app/core";

import { ArrowForwardIcon, CalendarIcon } from "../../ui/icons";
import { BrandTitle } from "../common/BrandTitle";
import { questionnairePath } from "../paths";
import { APP_TAGLINE } from "../shell/AppShell";
import { formatElectionDate } from "./format-date";
import { HowItWorksCarousel } from "./HowItWorksCarousel";
import { useElections, type ElectionsState } from "./useElections";

// Copy from the user (2026-11-06, landing-upcoming-copy).
// Hero lead as three points (copy from the user, 2026-11-06, landing-upcoming-copy).
const LEAD_POINTS = [
  "Responde al cuestionario.",
  "Descubre con quién concuerdan tus respuestas.",
  "Comprueba las citas sobre las afirmaciones en los programas.",
] as const;

// Landing screen (DESIGN.md Core Screens 1): a compact hero, the Elections
// grid (exactly what the API returns, in API order; the fixed 2026 upcoming
// card was removed when the 2026 Election was published) and the full-width `Cómo funciona` carousel (no section title; the
// methodology is in the sidebar). The AI
// disclosure lives in the shell footer and on /transparencia. No party names
// or colours in the page's own markup.
export function LandingPage({ api }: { readonly api: PublicApi }) {
  const { state, retry } = useElections(api);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Like every other page, focus the h1 on open, so an in-app navigation (a
  // drawer link, Volver al inicio) never leaves focus on <body>.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <main className="landing">
      <BrandTitle headingRef={headingRef} />
      <p className="brand-subtitle">{APP_TAGLINE}</p>
      <ul className="landing__lead">
        {LEAD_POINTS.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>

      <section aria-labelledby="elections-title">
        <div className="section-head">
          <h2 id="elections-title">Elecciones disponibles</h2>
        </div>
        <ElectionsList state={state} retry={retry} />
      </section>

      <HowItWorksCarousel />
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
        <div role="alert" className="card">
          <p>No se han podido cargar las elecciones. Comprueba tu conexión e inténtalo de nuevo.</p>
          <button type="button" className="button-primary" onClick={retry}>
            Reintentar
          </button>
        </div>
      );
    case "loaded":
      return (
        <>
          {state.elections.length === 0 ? (
            <p>Ahora mismo no hay elecciones disponibles. Vuelve a consultarlo más adelante.</p>
          ) : null}
          <ul className="election-list">
            {state.elections.map((election) => (
              <ElectionItem key={election.id} election={election} />
            ))}
          </ul>
        </>
      );
  }
}

// The whole card is one link (stretched over the card). No status chip
// (user decision 2026-11-03), except the rare `En preparación`, which sits
// outside the link so the link's name stays name, date and action.
function ElectionItem({ election }: { readonly election: Election }) {
  const published = election.publishedDatasetVersionId !== null;
  return (
    <li className="election-card">
      {published ? null : <span className="status-badge status-badge--muted">En preparación</span>}
      <Link className="election-link" to={questionnairePath(election.id)}>
        <span className="election-link__name">{election.name}</span>{" "}
        <span className="election-link__date">
          <CalendarIcon />
          {formatElectionDate(election.date)}
        </span>{" "}
        <span className="election-link__cta">
          <span>Realizar cuestionario</span>
          <ArrowForwardIcon />
        </span>
      </Link>
    </li>
  );
}
