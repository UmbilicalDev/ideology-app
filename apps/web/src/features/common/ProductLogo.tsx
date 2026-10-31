import logoDarkUrl from "../../assets/ideologiapp-logo.svg";
import logoLightUrl from "../../assets/ideologiapp-logo-light.svg";

/**
 * The product logo (DESIGN.md "Existing Design Assets"), decorative. Two
 * variants of the same drawing: the white ballot box for the dark theme (the
 * default) and the slate one under `prefers-color-scheme: light`, where white
 * would vanish on the light surfaces. Both are served from the app's own
 * /assets/.
 */
export function ProductLogo({ className, size }: { readonly className: string; readonly size: number }) {
  return (
    <picture>
      <source srcSet={logoLightUrl} media="(prefers-color-scheme: light)" />
      <img className={className} src={logoDarkUrl} alt="" width={size} height={size} />
    </picture>
  );
}
