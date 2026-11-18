// The site's holders and contact details (legal-privacy-page), as served by
// `GET /api/v1/legal-notice` from the server's `LEGAL_*` settings. Empty
// `holders` and null fields mean "not configured yet".

export interface LegalHolder {
  readonly name: string;
  /** The holder's DNI or NIE, or `null` when it is not published. */
  readonly nif: string | null;
}

export interface LegalNotice {
  readonly holders: readonly LegalHolder[];
  readonly contactEmail: string | null;
  readonly address: string | null;
}
