// Provisional copy: pending legal review before a public launch (docs/risks-and-open-questions.md, "Electoral and legal exposure").
import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { HOME_PATH } from "../paths";

export const METHODOLOGY_TITLE = "Metodología · Comparador de programas electorales";

// Methodology screen (DESIGN.md Core Screens 4). Static copy, no API request.
// It states the default Validation thresholds and the matching rule; keep it in
// sync with them (CONSTRAINTS.md, "Public Copy"). Names no party.
export function MethodologyPage() {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = METHODOLOGY_TITLE;
    headingRef.current?.focus();
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <main>
      <h1 ref={headingRef} tabIndex={-1}>
        Metodología
      </h1>
      <p>
        Esta página explica de dónde salen las afirmaciones y las posiciones de los partidos, cómo
        se comprueban antes de publicarse, cómo se calcula la afinidad y qué pasa con tus
        respuestas.
      </p>

      <section aria-labelledby="methodology-sources-title">
        <h2 id="methodology-sources-title">Programas electorales</h2>
        <p>
          Se usan los programas electorales de las candidaturas con representación en el Congreso
          de los Diputados, ya sean partidos o coaliciones, tal como se presentaron a las
          elecciones. Si el programa conjunto de una coalición contradice el de uno de sus
          partidos, la inteligencia artificial debe dar prioridad al programa conjunto.
        </p>
        <p>
          Las instrucciones que recibe la inteligencia artificial nunca incluyen el nombre del
          partido: solo el texto de su programa, que puede mencionarlo. Todos los programas se
          procesan con las mismas instrucciones.
        </p>
      </section>

      <section aria-labelledby="methodology-statements-title">
        <h2 id="methodology-statements-title">Cómo se redactan las afirmaciones</h2>
        <p>
          Una inteligencia artificial lee los programas por fragmentos y propone afirmaciones:
          propuestas políticas concretas con las que se puede estar de acuerdo o en desacuerdo.
          Después elige y redacta la lista final, de unas 30 afirmaciones, y asigna a cada una un
          tema.
        </p>
        <p>
          Sus instrucciones le piden una redacción neutral, sin adjetivos valorativos ni nombres de
          partidos o de políticos, una sola propuesta por afirmación, temas variados y,
          preferiblemente, propuestas en las que los partidos discrepen. Nadie modifica a mano el
          resultado.
        </p>
      </section>

      <section aria-labelledby="methodology-positions-title">
        <h2 id="methodology-positions-title">Cómo se sitúa a cada partido</h2>
        <p>
          La inteligencia artificial vuelve a leer el programa de cada partido y, en cada
          afirmación que el programa trata de forma explícita, le asigna una posición en una escala
          de cinco puntos, de «totalmente en desacuerdo» a «totalmente de acuerdo», y copia una
          cita literal del programa, con su página, que la respalda.
        </p>
        <p>
          Si el programa no trata una afirmación, el partido queda sin posición en ella: sus
          instrucciones le prohíben deducir la posición de la ideología general del partido.
        </p>
        <p>
          Podrás consultar la cita de cada posición para comprobarla. Las comprobaciones
          automáticas verifican que la cita está en el programa, pero no pueden confirmar que
          respalde la posición asignada; por eso es importante que puedas leerla.
        </p>
      </section>

      <section aria-labelledby="methodology-validation-title">
        <h2 id="methodology-validation-title">Comprobaciones antes de publicar</h2>
        <p>Antes de publicar los datos de unas elecciones, se comprueba automáticamente que:</p>
        <ul className="plain-list">
          <li>
            cada cita aparece literalmente en el programa del partido, empezando en la página
            indicada, sin tener en cuenta mayúsculas, tildes, espacios ni signos de puntuación;
          </li>
          <li>cada partido tiene posición en al menos el 70&nbsp;% de las afirmaciones;</li>
          <li>
            en cada afirmación hay al menos dos posiciones distintas entre los partidos que tienen
            posición;
          </li>
          <li>no hay dos afirmaciones con el mismo texto;</li>
          <li>el cuestionario tiene entre 25 y 35 afirmaciones;</li>
          <li>ningún tema reúne más del 30&nbsp;% de las afirmaciones.</li>
        </ul>
        <p>
          Si falla cualquiera de estas comprobaciones, no se publica nada y siguen vigentes los
          datos publicados anteriormente, si los hay. Una vez publicados, los datos no se modifican
          nunca: si se generan datos nuevos, sustituyen a los anteriores.
        </p>
      </section>

      <section aria-labelledby="methodology-matching-title">
        <h2 id="methodology-matching-title">Cómo se calcula la afinidad</h2>
        <p>
          Tus respuestas y las posiciones de los partidos usan la misma escala de cinco puntos. En
          cada afirmación, la coincidencia con un partido es del 100&nbsp;% si tu respuesta y su
          posición son iguales, y baja 25 puntos por cada paso de diferencia en la escala: es del
          0&nbsp;% entre «totalmente de acuerdo» y «totalmente en desacuerdo».
        </p>
        <p>
          La afinidad con cada partido es la media de esas coincidencias en las afirmaciones que
          respondes y en las que el partido tiene posición. Las afirmaciones que te saltes y
          aquellas en las que el partido no tiene posición no cuentan. Las que marques como
          importantes cuentan el doble.
        </p>
        <p>
          Si compartes menos de 5 afirmaciones con un partido, su afinidad se marca como de baja
          cobertura, porque se basa en pocos datos. Los partidos se ordenan por afinidad y, en caso
          de empate, alfabéticamente.
        </p>
      </section>

      <section aria-labelledby="methodology-privacy-title">
        <h2 id="methodology-privacy-title">Tus respuestas</h2>
        <p>
          Tus respuestas se quedan en tu navegador: no se envían ni se guardan en ningún servidor,
          y la afinidad se calcula en tu propio dispositivo. No hay cuentas de usuario ni
          estadísticas sobre las respuestas.
        </p>
        <p>
          Para volver a abrir o compartir un resultado se usará un enlace que lleva tus respuestas
          al final de la dirección, tras el símbolo «#». Los navegadores no envían esa parte de la
          dirección al servidor.
        </p>
      </section>

      <section className="card" aria-labelledby="methodology-disclaimer-title">
        <h2 id="methodology-disclaimer-title">Aviso</h2>
        <p>
          Esta herramienta no es una recomendación de voto. Las afirmaciones y las posiciones las
          genera automáticamente una inteligencia artificial, sin revisión humana, y pueden
          contener errores. La afinidad solo refleja lo que dicen los programas electorales, no lo
          que los partidos han hecho o votado. Contrasta las citas con los programas originales
          antes de sacar conclusiones.
        </p>
      </section>

      <p>
        <Link className="back-link" to={HOME_PATH}>
          Volver al inicio
        </Link>
      </p>
    </main>
  );
}
