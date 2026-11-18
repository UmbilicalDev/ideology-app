import { useContext } from "react";

import { DonationLink } from "./DonationLink";
import { DonationUrlContext } from "./donation-context";

export const DONATION_QUESTION = "¿Quieres apoyar el proyecto?";
export const DONATION_DISCLOSURE = "¿Para qué se usan las donaciones?";

/**
 * The low-key donation block that ends the results screen (DESIGN.md
 * "Donation link and block"): the question with the link, then a native
 * disclosure, closed by default, below it so opening it never moves the
 * link. Nothing at all when no donation link is configured. Not on the
 * Shared Results page.
 */
export function DonationBlock() {
  const url = useContext(DonationUrlContext);
  if (url === null) {
    return null;
  }
  return (
    <div className="donate-block">
      <p className="donate-block__line">
        {DONATION_QUESTION} <DonationLink url={url} className="text-link" />
      </p>
      <details className="donate-block__details">
        <summary className="donate-block__summary">{DONATION_DISCLOSURE}</summary>
        <p>
          Donar es una forma sencilla de apoyar IdeologiApp y de ayudarla a crecer: con las
          donaciones añadimos funciones nuevas o mejoramos las que ya hay, y pagamos el alojamiento
          de la web.
        </p>
        <p>
          No aceptamos donaciones hechas en nombre de partidos políticos. Si detectamos una donación
          hecha en nombre de un partido político, la devolveremos.
        </p>
      </details>
    </div>
  );
}
