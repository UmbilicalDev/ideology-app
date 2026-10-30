import bulbUrl from "../../assets/ideologiapp-bulb.svg";
import logoUrl from "../../assets/ideologiapp-logo.svg";

export const APP_NAME = "IdeologiApp";

/**
 * The brand page title (DESIGN.md "Typography" and "brand-title"): the
 * product logo, served from the app's own /assets/, and its name. The logo is
 * decorative; the name is the heading's text. On the Landing's blue brand
 * header (`onBrand`) the logo is the bulb alone, larger, without its blue tile.
 */
export function BrandTitle({ onBrand = false }: { readonly onBrand?: boolean }) {
  return (
    <h1 className={onBrand ? "brand-title brand-title--on-brand" : "brand-title"}>
      <img
        className="brand-title__logo"
        src={onBrand ? bulbUrl : logoUrl}
        alt=""
        width="48"
        height="48"
      />
      <span>{APP_NAME}</span>
    </h1>
  );
}
