// Provisional copy: pending legal review before a public launch (docs/risks-and-open-questions.md, "Electoral and legal exposure").
import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { CheckCircleIcon, ChipIcon, ShieldIcon } from "../../ui/icons";
import { HomeButton } from "../common/HomeButton";
import { METHODOLOGY_PATH } from "../paths";

export const TRANSPARENCY_TITLE = "Transparencia IA · IdeologiApp";

// Transparency screen (DESIGN.md Core Screens 6). Static copy, no API
// request: a short summary of what the AI does and does not do, drawn from
// the methodology page, which stays the full public description of the
// method (CONSTRAINTS.md, "Public Copy"). Names no party.
export function TransparencyPage() {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = TRANSPARENCY_TITLE;
    headingRef.current?.focus();
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <main className="doc-page">
      <div className="doc-page__header">
        <h1 ref={headingRef} tabIndex={-1}>
          Transparencia IA
        </h1>
        <p className="doc-page__lead">
          Qué hace la inteligencia artificial en esta herramienta, qué se comprueba antes de
          publicar sus resultados y qué no puede garantizar.
        </p>
      </div>

      <div className="feature-grid">
        <section className="card feature-card" aria-labelledby="transparency-ai-title">
          <span className="feature-card__icon">
            <ChipIcon />
          </span>
          <h2 id="transparency-ai-title">Qué genera la IA</h2>
          <p>
            Una inteligencia artificial lee los programas electorales de los partidos con
            representación en el Congreso, redacta las afirmaciones del cuestionario y, en cada
            afirmación que trata el programa de un partido, le asigna una posición con una cita
            literal como prueba; si el programa no la trata, el partido queda sin posición. Nadie
            modifica a mano el resultado.
          </p>
        </section>

        <section className="card feature-card" aria-labelledby="transparency-checks-title">
          <span className="feature-card__icon">
            <CheckCircleIcon />
          </span>
          <h2 id="transparency-checks-title">Qué se comprueba</h2>
          <p>
            Antes de publicar los datos, unas comprobaciones automáticas verifican, entre otras
            cosas, que cada cita aparece literalmente en el programa del partido. Si falla alguna,
            no se publica nada.
          </p>
        </section>

        <section className="card feature-card" aria-labelledby="transparency-privacy-title">
          <span className="feature-card__icon">
            <ShieldIcon />
          </span>
          <h2 id="transparency-privacy-title">Tus respuestas</h2>
          <p>
            Tus respuestas se quedan en tu navegador: no se envían ni se guardan en ningún
            servidor, y la afinidad se calcula en tu propio dispositivo.
          </p>
        </section>
      </div>

      <section className="card notice-panel" aria-labelledby="transparency-limits-title">
        <h2 id="transparency-limits-title">Lo que no puede garantizar</h2>
        <ul className="plain-list">
          <li>
            Las afirmaciones y las posiciones se generan sin revisión humana y pueden contener
            errores.
          </li>
          <li>
            Las comprobaciones verifican que la cita está en el programa, pero no que respalde la
            posición asignada: en los resultados puedes leer cada cita y comprobarla.
          </li>
          <li>
            La afinidad solo refleja lo que dicen los programas electorales, no lo que los partidos
            han hecho o votado.
          </li>
          <li>Esta herramienta no es una recomendación de voto.</li>
        </ul>
      </section>

      <p>
        <Link className="text-link" to={METHODOLOGY_PATH}>
          Lee la metodología completa
        </Link>
      </p>
      <HomeButton />
    </main>
  );
}
