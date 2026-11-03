import type { ReactNode } from "react";
import { Link } from "react-router";

import { CloseIcon } from "../../ui/icons";
import { APP_NAME } from "../common/BrandTitle";
import { ProductLogo } from "../common/ProductLogo";
import { HOME_PATH } from "../paths";

/**
 * The Questionnaire's layout (DESIGN.md "Focus shell"): no sidebar, only a
 * slim bar with the brand (a link home) and `Salir`, and one centred column.
 * Answers live in page state, so leaving by either link discards them.
 */
export function FocusShell({ children }: { readonly children: ReactNode }) {
  return (
    <div className="focus-shell">
      <header className="focus-bar">
        <Link className="focus-bar__brand" to={HOME_PATH} aria-label={`${APP_NAME}, ir al inicio`}>
          <ProductLogo className="focus-bar__logo" size={28} />
          <span>{APP_NAME}</span>
        </Link>
        <Link className="focus-bar__exit" to={HOME_PATH}>
          <CloseIcon />
          <span>Salir</span>
        </Link>
      </header>
      <div className="focus-shell__content">{children}</div>
    </div>
  );
}
