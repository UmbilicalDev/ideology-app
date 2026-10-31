import type { Ref } from "react";

import { ProductLogo } from "./ProductLogo";

export const APP_NAME = "IdeologiApp";

/**
 * The brand page title (DESIGN.md "Typography" and "brand-title"): the
 * product logo, served from the app's own /assets/, and its name. The logo is
 * decorative; the name is the heading's text. With `headingRef` the page can
 * focus it on open (it is then focusable by script only).
 */
export function BrandTitle({ headingRef }: { readonly headingRef?: Ref<HTMLHeadingElement> }) {
  return (
    <h1 className="brand-title" ref={headingRef} tabIndex={headingRef === undefined ? undefined : -1}>
      <ProductLogo className="brand-title__logo" size={48} />
      <span>{APP_NAME}</span>
    </h1>
  );
}
