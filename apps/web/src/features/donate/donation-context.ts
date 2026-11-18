import { createContext } from "react";

/**
 * The donation link for every page (donate-buymeacoffee): the configured
 * `DONATION_URL`, or `null` while loading, on any error and when unset.
 * Provided once by `App`; the sidebar, the end screen and `/legal` read it.
 */
export const DonationUrlContext = createContext<string | null>(null);
