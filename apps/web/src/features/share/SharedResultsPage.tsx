import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { HOME_PATH } from "../paths";

// Placeholder for `/resultados` until `share-link-open` replaces this body
// (keep the file and the route). It never reads the fragment, takes no `api`
// and makes no request.
export function SharedResultsPage() {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <main>
      <h1 ref={headingRef} tabIndex={-1}>
        Resultado compartido
      </h1>
      <p>
        Todavía no se pueden abrir resultados compartidos. Puedes responder el cuestionario tú
        mismo desde el inicio.
      </p>
      <p>
        <Link className="back-link" to={HOME_PATH}>
          Volver al inicio
        </Link>
      </p>
    </main>
  );
}
