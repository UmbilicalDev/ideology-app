// Provisional copy: pending legal review before a public launch (docs/risks-and-open-questions.md, "Electoral and legal exposure").
import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { HomeButton } from "../common/HomeButton";
import { PageToc, type TocEntry } from "../common/PageToc";
import { LEGAL_PATH } from "../paths";

export const METHODOLOGY_TITLE = "Metodología · IdeologiApp";

const TOC: readonly TocEntry[] = [
  { id: "methodology-sources-title", label: "Programas electorales" },
  { id: "methodology-statements-title", label: "Las afirmaciones" },
  { id: "methodology-positions-title", label: "La posición de cada partido" },
  { id: "methodology-selection-title", label: "El cuestionario" },
  { id: "methodology-validation-title", label: "Comprobaciones" },
  { id: "methodology-matching-title", label: "La afinidad" },
  { id: "methodology-privacy-title", label: "Tus respuestas" },
  { id: "methodology-disclaimer-title", label: "Aviso" },
];

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
    <main className="doc-page">
      <div className="doc-page__header">
        <h1 ref={headingRef} tabIndex={-1}>
          Metodología
        </h1>
        <p className="doc-page__lead">
          Esta página explica de dónde salen las afirmaciones y las posiciones de los partidos, cómo
          se comprueban antes de publicarse, cómo se calcula la afinidad y qué pasa con tus
          respuestas.
        </p>
      </div>
      <div className="doc-page__layout">
        <PageToc entries={TOC} />
        <div className="doc-page__body">
          <section aria-labelledby="methodology-sources-title">
            <h2 id="methodology-sources-title">Programas electorales</h2>
            <p>
              Se usan los programas electorales de las candidaturas con representación en el
              Congreso de los Diputados, ya sean partidos o coaliciones, tal como se presentaron a
              las elecciones. Si el programa conjunto de una coalición contradice el de uno de sus
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
              Una inteligencia artificial lee los programas por fragmentos y recoge como
              afirmaciones candidatas todas las propuestas políticas concretas que encuentra, hasta
              30 por fragmento: propuestas con las que se puede estar de acuerdo o en desacuerdo.
              Después, un procedimiento automático, sin inteligencia artificial y sin
              azar, toma el mismo número de candidatas de cada partido, sea cual sea la extensión de
              su programa, repartidas entre los temas que más trata cada programa. Un partido con
              menos candidatas aporta todas las que tiene.
            </p>
            <p>
              Con esas candidatas, la inteligencia artificial redacta una lista más amplia, de unas
              120 afirmaciones, y asigna a cada una un tema. Cada afirmación expresa una orientación
              política con una dirección clara, como subir o bajar un impuesto, y no una medida de
              detalle, para que el mayor número posible de partidos se pueda situar en ella. Debe
              entenderse por sí sola y en lenguaje llano: expresa la medida por su contenido y en
              positivo, de modo que estar de acuerdo signifique querer esa medida, sin dobles
              negaciones; solo habla de derogar o suprimir algo cuando la propuesta no tiene otro
              contenido.
            </p>
            <p>
              La inteligencia artificial recibe también las afirmaciones del cuestionario publicado
              anteriormente y las vuelve a redactar con estas reglas, para que los temas que ya
              conoces no desaparezcan por azar. Siguen en el cuestionario solo si superan el mismo
              procedimiento de elección que las demás.
            </p>
            <p>
              Cada afirmación lleva una breve nota de contexto, también redactada por la
              inteligencia artificial, que explica de forma neutral qué es la ley, el plan, la
              institución o el concepto que nombra. La nota no sale de los programas, y las
              comprobaciones automáticas no pueden confirmar que sea exacta; sus instrucciones le
              piden solo hechos descriptivos, sin valoraciones ni nombres de partidos.
            </p>
            <p>
              Sus instrucciones le piden una redacción neutral, sin adjetivos valorativos ni nombres
              de partidos o de políticos, una sola propuesta por afirmación, temas variados,
              orientaciones en las que unos partidos estén a favor y otros en contra, mejor si las
              tratan muchos programas, y no añadir nada que no esté en las
              candidatas ni en las afirmaciones anteriores. Nadie modifica a mano el resultado.
            </p>
          </section>

          <section aria-labelledby="methodology-positions-title">
            <h2 id="methodology-positions-title">Cómo se sitúa a cada partido</h2>
            <p>
              La inteligencia artificial vuelve a leer el programa de cada partido y, en cada
              afirmación que el programa trata de forma explícita, le asigna una posición en una
              escala de cinco puntos, de «totalmente en desacuerdo» a «totalmente de acuerdo», y
              copia una cita literal del programa, con su página, que la respalda. Si esa copia
              tiene una pequeña errata o indica otra página del fragmento que leía, se guarda en su
              lugar el texto exacto del programa y su página; la posición no cambia.
            </p>
            <p>
              Para calcular la afinidad solo cuenta de qué lado está la posición: a favor o en
              contra. La intensidad se ve en la cita.
            </p>
            <p>
              Si el programa no trata una afirmación, el partido queda sin posición en ella: sus
              instrucciones le prohíben deducir la posición de la ideología general del partido o de
              que el programa no mencione el asunto. Sí cuenta como tratarla una propuesta concreta
              del programa que va claramente en la dirección de la afirmación o en la contraria, y
              la cita debe contener esa propuesta.
            </p>
            <p>
              En los resultados puedes abrir la posición de cada partido en cada afirmación para
              leer la cita y comprobarla. Las comprobaciones automáticas verifican que la cita está
              en el programa, pero no pueden confirmar que respalde la posición asignada; por eso es
              importante que puedas leerla.
            </p>
          </section>

          <section aria-labelledby="methodology-selection-title">
            <h2 id="methodology-selection-title">Cómo se eligen las afirmaciones del cuestionario</h2>
            <p>
              La inteligencia artificial propone más afirmaciones de las que tendrá el cuestionario,
              entre 100 y 140, y sitúa a cada partido en todas ellas. Después, un procedimiento
              automático, sin inteligencia artificial y sin azar, elige hasta 40 y las ordena.
            </p>
            <p>
              Deja fuera las afirmaciones cuya nota de contexto no cumple las comprobaciones, las
              repetidas, las que no separan a los partidos, porque no hay al menos uno a favor y
              otro en contra, y aquellas en las que menos de 3 partidos están a favor o en contra.
              Ordena las demás por el número de partidos que están a favor o en contra; en caso de
              empate, primero las más repartidas entre los dos lados y, después, las que se
              propusieron antes. Todos los partidos cuentan igual.
            </p>
            <p>
              Así, las primeras afirmaciones son las que tratan más partidos, y las comprobaciones
              se aplican también a las primeras 15 y a las primeras 30, para que un cuestionario más
              corto, formado por las primeras, sea igual de equilibrado. Ningún tema supera el
              30&nbsp;% de las primeras 15, de las primeras 30 ni del total: una afirmación que lo
              superaría pasa al primer puesto en el que cabe.
            </p>
            <p>
              El cuestionario completo tiene entre 35 y 40 afirmaciones: el mayor número con el que
              todos los partidos están a favor o en contra en al menos el 50&nbsp;% de ellas. Si no
              es posible cumplir estas condiciones, el procedimiento se acerca todo lo que puede y
              las comprobaciones posteriores impiden publicar el resultado. Las afirmaciones
              conservan el texto con que se propusieron.
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
              <li>
                cada partido está a favor o en contra en al menos el 50&nbsp;% de las afirmaciones,
                y también de las primeras 15 y de las primeras 30;
              </li>
              <li>en cada afirmación hay al menos un partido a favor y otro en contra;</li>
              <li>no hay dos afirmaciones con el mismo texto;</li>
              <li>el cuestionario completo tiene entre 35 y 40 afirmaciones;</li>
              <li>
                ningún tema reúne más del 30&nbsp;% de las afirmaciones, ni de las primeras 15 ni de
                las primeras 30;
              </li>
              <li>
                cada afirmación tiene una nota de contexto de entre 30 y 300 caracteres que no usa
                ninguna palabra valorativa de una lista fija.
              </li>
            </ul>
            <p>
              Si falla cualquiera de estas comprobaciones, no se publica nada y siguen vigentes los
              datos publicados anteriormente, si los hay. Una vez publicados, los datos no se
              modifican nunca: si se generan datos nuevos, sustituyen a los anteriores.
            </p>
          </section>

          <section aria-labelledby="methodology-matching-title">
            <h2 id="methodology-matching-title">Cómo se calcula la afinidad</h2>
            <p>
              Respondes cada afirmación con una de tres opciones: «De acuerdo», «En desacuerdo» o
              «Neutral / No lo sé». La posición de cada partido se lee por su lado: a favor si está
              de acuerdo o muy de acuerdo, en contra si está en desacuerdo o muy en desacuerdo.
            </p>
            <p>
              En cada afirmación, si tú y el partido estáis del mismo lado, cuenta como una
              coincidencia (1); si estáis en lados opuestos, no coincide (0). No cuentan las
              afirmaciones en las que respondes «Neutral / No lo sé», ni aquellas en las que el
              partido no tiene posición o tiene una posición neutral. Las que marques como
              importantes cuentan el doble.
            </p>
            <p>
              Puedes marcar como importantes hasta un tercio de las afirmaciones, redondeando hacia
              arriba. Si respondes «Neutral / No lo sé» a una afirmación marcada, la marca se quita,
              porque no contaría.
            </p>
            <p>
              Cada partido muestra «N de M coincidencias»: M son las afirmaciones que se pueden
              comparar con ese partido y N aquellas en las que coincidís. La afinidad es el
              porcentaje de coincidencias; si marcas afirmaciones como importantes, el porcentaje
              las pondera, así que puede diferir un poco de N entre M.
            </p>
            <p>
              Si se pueden comparar menos de 5 afirmaciones con un partido, su afinidad se marca
              como de baja cobertura, porque se basa en pocos datos. Los partidos se ordenan por
              afinidad y, en caso de empate, alfabéticamente.
            </p>
          </section>

          <section aria-labelledby="methodology-privacy-title">
            <h2 id="methodology-privacy-title">Tus respuestas</h2>
            <p>
              Tus respuestas se quedan en tu navegador: no se envían ni se guardan en ningún
              servidor, y la afinidad se calcula en tu propio dispositivo. No hay cuentas de usuario
              ni estadísticas sobre las respuestas.
            </p>
            <p>
              Puedes compartir tu resultado con un enlace que lleva tus respuestas al final de la
              dirección, tras el símbolo «#». Los navegadores no envían esa parte de la dirección al
              servidor y el enlace no se guarda en ningún sitio: quien lo tenga puede ver tus
              respuestas. Al abrir el enlace se ve el mismo resultado, calculado de nuevo en el
              navegador con la misma versión del cuestionario; si después se ha publicado una más
              reciente, se avisa. Los enlaces creados antes del cuestionario de tres opciones
              muestran un aviso en lugar del resultado.
            </p>
            <p>
              Si nos envías tu opinión sobre la herramienta, se guarda solo el texto que escribas,
              desde dónde la envías (el menú general o la pantalla de resultados) y la fecha. No se
              guardan tus respuestas, tu dirección IP ni ningún otro dato sobre ti. Para frenar los
              envíos masivos, el servidor cuenta durante unos minutos, solo en memoria, los envíos
              de cada conexión. No escribas datos personales en el mensaje.
            </p>
            <p>
              Quién es responsable, cuánto tiempo se guardan las opiniones y cómo ejercer tus
              derechos se explica en{" "}
              <Link className="text-link" to={LEGAL_PATH}>
                Aviso legal y privacidad
              </Link>
              .
            </p>
          </section>

          <section className="card" aria-labelledby="methodology-disclaimer-title">
            <h2 id="methodology-disclaimer-title">Aviso</h2>
            <p>
              Esta herramienta no es una recomendación de voto. Las afirmaciones y las posiciones
              las genera automáticamente una inteligencia artificial, sin revisión humana, y pueden
              contener errores. La afinidad solo refleja lo que dicen los programas electorales, no
              lo que los partidos han hecho o votado. Contrasta las citas con los programas
              originales antes de sacar conclusiones.
            </p>
          </section>

          <HomeButton />
        </div>
      </div>
    </main>
  );
}
