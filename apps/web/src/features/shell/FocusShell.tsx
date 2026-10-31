import type { ReactNode } from "react";
import { Link } from "react-router";

import { CloseIcon } from "../../ui/icons";
import { APP_NAME } from "../common/BrandTitle";
import { ProductLogo } from "../common/ProductLogo";
import { HOME_PATH } from "../paths";

/**
 * The Questionnaire's layout (DESIGN.md "Focus shell"): no sidebar, only a
 * slim bar with the brand and `Salir`, and one centred column. Answers live
 * in page state, so there is no navigation to lose them by a stray click.
 */
export function FocusShell({ children }: { readonly children: ReactNode }) {
  return (
    <div className="focus-shell">
      <header className="focus-bar">
        <span className="focus-bar__brand">
          <ProductLogo className="focus-bar__logo" size={28} />
          <span>{APP_NAME}</span>
        </span>
        <Link className="focus-bar__exit" to={HOME_PATH}>
          <CloseIcon />
          <span>Salir</span>
        </Link>
      </header>
      <div className="focus-shell__content">{children}</div>
    </div>
  );
}
