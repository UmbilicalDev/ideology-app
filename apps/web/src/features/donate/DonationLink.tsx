import { CoffeeIcon, ExternalLinkIcon } from "../../ui/icons";

export const DONATION_LINK_TEXT = "Invítanos a un café";

/**
 * `Invítanos a un café` (DESIGN.md "Donation link and block"): a plain link
 * to exactly the configured URL in a new tab. `noreferrer` keeps even the
 * page path from Buy Me a Coffee; nothing from that site is loaded. It gets
 * only the URL, never Questionnaire state.
 */
export function DonationLink({ url, className }: { readonly url: string; readonly className: string }) {
  return (
    <a className={className} href={url} target="_blank" rel="noopener noreferrer">
      <CoffeeIcon />
      <span>{DONATION_LINK_TEXT}</span>{" "}
      <span className="visually-hidden">(se abre en una pestaña nueva)</span>
      <ExternalLinkIcon />
    </a>
  );
}
