// Provisional copy: pending review by a lawyer (docs/risks-and-open-questions.md, "Electoral and legal exposure").
import { useContext, useEffect, useRef } from "react";
import { Link } from "react-router";

import { FEEDBACK_RETENTION_MONTHS, type LegalNotice, type PublicApi } from "@ideology-app/core";

import { HomeButton } from "../common/HomeButton";
import { DonationUrlContext } from "../donate/donation-context";
import { PageToc, type TocEntry } from "../common/PageToc";
import { METHODOLOGY_PATH, TRANSPARENCY_PATH } from "../paths";
import { useLegalNotice } from "./useLegalNotice";

export const LEGAL_TITLE = "Aviso legal y privacidad · IdeologiApp";
// The date of the last change to this page's copy.
export const LEGAL_LAST_UPDATED = "18 de noviembre de 2026";

const TOC: readonly TocEntry[] = [
  { id: "legal-holders-title", label: "Titulares y contacto" },
  { id: "legal-terms-title", label: "Condiciones de uso" },
  { id: "legal-privacy-title", label: "Privacidad" },
  { id: "legal-cookies-title", label: "Cookies" },
];

// Legal notice, privacy policy and cookie statement (DESIGN.md Core Screens
// 8). Static copy except the holders and contact, which come from the
// server's LEGAL_* settings through `getLegalNotice`. Every statement here
// must stay true of the code (CONSTRAINTS.md, "Public Copy"): feedback store
// fields, the abuse guard's sweep, cookies and storage, the hosting provider,
// FEEDBACK_RETENTION_MONTHS and the donation channel (donate-buymeacoffee:
// its copy shows only when DONATION_URL is configured). Names no party.
export function LegalPage({ api }: { readonly api: PublicApi }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { state, retry } = useLegalNotice(api);
  const donationConfigured = useContext(DonationUrlContext) !== null;

  useEffect(() => {
    const previousTitle = document.title;
    document.title = LEGAL_TITLE;
    headingRef.current?.focus();
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <main className="doc-page">
      <div className="doc-page__header">
        <h1 ref={headingRef} tabIndex={-1}>
          Aviso legal y privacidad
        </h1>
        <p className="doc-page__lead">
          Quién es responsable de IdeologiApp, en qué condiciones puedes usarla, qué datos tratamos y
          qué se guarda en tu navegador.
        </p>
        <p className="doc-page__updated">Última actualización: {LEGAL_LAST_UPDATED}</p>
      </div>
      <div className="doc-page__layout">
        <PageToc entries={TOC} />
        <div className="doc-page__body">
          <section aria-labelledby="legal-holders-title">
            <h2 id="legal-holders-title">Titulares y contacto</h2>
            {state.kind === "loading" ? (
              <p role="status">Cargando los datos de los titulares…</p>
            ) : state.kind === "error" ? (
              <>
                <p role="alert">No se han podido cargar los datos de los titulares y de contacto.</p>
                <p>
                  <button type="button" className="button-primary" onClick={retry}>
                    Reintentar
                  </button>
                </p>
              </>
            ) : (
              <HoldersAndContact notice={state.notice} />
            )}
          </section>

          <section aria-labelledby="legal-terms-title">
            <h2 id="legal-terms-title">Condiciones de uso</h2>
            <p>
              Puedes usar IdeologiApp gratis y sin registrarte. Al usarla aceptas estas condiciones,
              que se rigen por la ley española.
            </p>
            {donationConfigured ? (
              <p>
                Las donaciones son voluntarias: puedes usar IdeologiApp igual sin donar, y donar no
                cambia las afirmaciones, las posiciones de los partidos ni ningún resultado. No
                aceptamos donaciones hechas en nombre de partidos políticos. Si detectamos una
                donación hecha en nombre de un partido político, la devolveremos.
              </p>
            ) : null}
            <p>
              IdeologiApp no es una recomendación de voto. Las afirmaciones del cuestionario y las
              posiciones de los partidos las genera automáticamente una inteligencia artificial a
              partir de los programas electorales, sin revisión humana, y pueden contener errores.
              La afinidad solo refleja lo que dicen los programas, no lo que los partidos han hecho
              o votado. Cómo se generan y se comprueban se explica en{" "}
              <Link className="text-link" to={METHODOLOGY_PATH}>
                Metodología
              </Link>{" "}
              y en{" "}
              <Link className="text-link" to={TRANSPARENCY_PATH}>
                Transparencia IA
              </Link>
              .
            </p>
            <p>
              Cada posición se respalda con una cita literal del programa electoral del partido, con
              su página, reproducida con fines de análisis y comentario al amparo del derecho de
              cita (artículo 32 de la Ley de Propiedad Intelectual). Los programas pertenecen a sus
              autores. Los logotipos de los partidos se muestran solo para identificarlos:
              pertenecen a sus titulares y su uso no implica relación con ellos ni su apoyo.
            </p>
            <p>
              Ofrecemos la herramienta tal cual, sin garantía de que su contenido sea exacto,
              completo o actual. En la medida en que la ley lo permite, no respondemos de las
              decisiones que tomes a partir de ella ni de los daños derivados de su uso. Los enlaces
              a programas electorales y a otros sitios llevan a páginas de terceros, de cuyo
              contenido no somos responsables.
            </p>
          </section>

          <section aria-labelledby="legal-privacy-title">
            <h2 id="legal-privacy-title">Política de privacidad</h2>
            <h3>Responsables</h3>
            <p>
              Los responsables del tratamiento son los titulares indicados en «Titulares y
              contacto», como corresponsables. Han acordado que cualquiera de ellos atiende las
              solicitudes que se envíen a la dirección de contacto.
            </p>
            <h3>Tus respuestas no salen de tu dispositivo</h3>
            <p>
              Tus respuestas al cuestionario, las afirmaciones que marcas como importantes y tu
              resultado no se envían a ningún servidor ni se guardan: la afinidad se calcula en tu
              navegador, así que no tratamos tus opiniones políticas. Si compartes tu resultado, el
              enlace lleva tus respuestas tras el símbolo «#», una parte de la dirección que los
              navegadores no envían al servidor; quien tenga el enlace puede verlas.
            </p>
            <h3>Qué datos tratamos</h3>
            <ul className="plain-list">
              <li>
                Las opiniones que nos envías con «Danos tu opinión», que es voluntario: guardamos
                solo el texto, desde dónde la envías (el menú general o la pantalla de resultados),
                la fecha y, cuando la revisamos, la fecha de revisión. No escribas en el mensaje
                datos personales ni opiniones políticas, tuyas o de otras personas.
              </li>
              <li>
                Tu dirección IP, que, como en cualquier web, recibe el servidor para enviarte la
                página. No guardamos registros de acceso. Al enviar una opinión, el servidor
                convierte tu dirección IP en un código del que no se puede recuperar para limitar
                los envíos masivos; ese código se guarda solo en la memoria del servidor, nunca en
                disco, y se descarta a partir de los 10 minutos.
              </li>
            </ul>
            <h3>Para qué y con qué base legal</h3>
            <p>
              Usamos las opiniones para mejorar la herramienta, el código de tu dirección IP para
              protegerla de envíos masivos y tu dirección IP para servir la web. La base legal es
              nuestro interés legítimo en mantener un servicio útil y seguro (artículo 6.1.f del
              Reglamento General de Protección de Datos). No usamos los datos para nada más, no
              hacemos perfiles ni tomamos decisiones automatizadas sobre ti.
            </p>
            <h3>Cuánto tiempo los guardamos</h3>
            <p>
              Guardamos cada opinión un máximo de {FEEDBACK_RETENTION_MONTHS} meses desde que la
              recibimos, y después la borramos, también de las copias de seguridad. Podemos borrarla
              antes.
            </p>
            <h3>Quién más accede a los datos</h3>
            <p>
              Solo los titulares, a través de una página de administración protegida con
              contraseña. La web se aloja en un servidor de Netcup GmbH en Alemania, que actúa como
              encargado del tratamiento. Los datos no salen de la Unión Europea y no los cedemos a
              nadie, salvo obligación legal. Si compartes IdeologiApp con los botones de otras redes
              o aplicaciones, se abre el servicio que elijas, que trata tus datos según su propia
              política; solo se comparte la dirección de IdeologiApp.
            </p>
            {donationConfigured ? (
              <>
                <h3>Donaciones</h3>
                <p>
                  El enlace «Invítanos a un café» abre en una pestaña nueva la página del proyecto en
                  Buy Me a Coffee, un servicio de otra empresa. Es un enlace normal: IdeologiApp no
                  carga nada de Buy Me a Coffee, no registra si lo abres y no le envía tus respuestas
                  ni la página desde la que llegas.
                </p>
                <p>
                  Si donas, lo haces en Buy Me a Coffee, con sus propias condiciones y su política de
                  privacidad, y es ese servicio el que trata tus datos de pago. Las donaciones las
                  recibe uno de los titulares en su cuenta de Buy Me a Coffee; de cada donación solo
                  vemos lo que ese servicio muestra a quien la recibe y lo usamos únicamente para
                  gestionarla y agradecerla.
                </p>
              </>
            ) : null}
            <h3>Tus derechos</h3>
            <p>
              Puedes pedirnos el acceso a tus datos, su rectificación o supresión, la limitación de
              su tratamiento o su portabilidad, y oponerte a su tratamiento, escribiendo a la
              dirección de contacto. Como no guardamos nada que te identifique, para localizar una
              opinión indícanos su texto y la fecha aproximada de envío. También puedes reclamar
              ante la Agencia Española de Protección de Datos en{" "}
              <a className="text-link" href="https://www.aepd.es/">
                www.aepd.es
              </a>
              .
            </p>
          </section>

          <section aria-labelledby="legal-cookies-title">
            <h2 id="legal-cookies-title">Cookies y almacenamiento</h2>
            <p>
              Las páginas públicas de IdeologiApp no instalan cookies ni usan el almacenamiento de
              tu navegador (almacenamiento local, de sesión o IndexedDB), y no cargan nada de otros
              sitios: ni analítica, ni publicidad, ni fuentes, ni redes sociales. Tu navegador solo
              guarda en su caché los archivos de la web, como en cualquier sitio, para cargarla más
              rápido.
            </p>
            <p>
              La única cookie es la de sesión de la página de administración, que solo reciben los
              titulares al iniciar sesión. Es técnica e imprescindible para ese acceso, no se envía
              en las páginas públicas y caduca al cerrar la sesión o el navegador, por lo que no
              requiere consentimiento.
            </p>
            <p>
              Si algún día añadimos estadísticas u otras cookies que no sean técnicas, te pediremos
              antes tu consentimiento y lo indicaremos aquí.
            </p>
          </section>

          <HomeButton />
        </div>
      </div>
    </main>
  );
}

/** The dynamic part of `Titulares y contacto`: pending sentences when a value is not configured. */
function HoldersAndContact({ notice }: { readonly notice: LegalNotice }) {
  return (
    <>
      {notice.holders.length === 0 ? (
        <p>Los nombres de los titulares están pendientes de publicación.</p>
      ) : (
        <>
          <p>
            IdeologiApp es un proyecto de personas físicas, no de una empresa ni de una asociación.
            Sus titulares, que lo gestionan conjuntamente y son corresponsables del tratamiento de
            los datos descrito en esta página, son:
          </p>
          <ul className="plain-list">
            {notice.holders.map((holder, index) => (
              <li key={index}>
                {holder.nif === null ? holder.name : `${holder.name}, NIF ${holder.nif}`}
              </li>
            ))}
          </ul>
        </>
      )}
      {notice.address === null ? null : <p>Dirección postal: {notice.address}</p>}
      {notice.contactEmail === null ? (
        <p>La dirección de contacto está pendiente de publicación.</p>
      ) : (
        <p>
          Contacto:{" "}
          <a className="text-link" href={`mailto:${notice.contactEmail}`}>
            {notice.contactEmail}
          </a>
          . Escríbenos para cualquier consulta sobre esta página o para ejercer tus derechos.
        </p>
      )}
    </>
  );
}
