import { Link } from "react-router";

import { HOME_PATH } from "../paths";

export function NotFoundPage() {
  return (
    <main>
      <h1>Página no encontrada</h1>
      <p>Esta dirección no corresponde a ninguna página.</p>
      <p>
        <Link className="back-link" to={HOME_PATH}>
          Volver al inicio
        </Link>
      </p>
    </main>
  );
}
