import logoUrl from "../../assets/ideologiapp-logo.svg";

export const APP_NAME = "IdeologiApp";

/**
 * The brand page title (DESIGN.md "Typography" and "brand-title"): the
 * product logo, served from the app's own /assets/, and its name. The logo is
 * decorative; the name is the heading's text.
 */
export function BrandTitle() {
  return (
    <h1 className="brand-title">
      <img className="brand-title__logo" src={logoUrl} alt="" width="48" height="48" />
      <span>{APP_NAME}</span>
    </h1>
  );
}
