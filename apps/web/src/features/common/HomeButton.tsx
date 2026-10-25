import { Link } from "react-router";

import { HOME_PATH } from "../paths";

/** `Volver al inicio` as an outlined button (DESIGN.md "Buttons"); still a link. */
export function HomeButton() {
  return (
    <p>
      <Link className="button-secondary" to={HOME_PATH}>
        Volver al inicio
      </Link>
    </p>
  );
}
