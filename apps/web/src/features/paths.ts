// Client routes, defined once. Segments never contain a "." because the
// server's SPA fallback answers such paths with 404 (see CONSTRAINTS.md).
export const HOME_PATH = "/";
export const QUESTIONNAIRE_ROUTE = "/elecciones/:electionId/cuestionario";

const MAX_ELECTION_ID = 2147483647; // the API's id bound
const ELECTION_ID_PATTERN = /^[1-9][0-9]{0,9}$/;

export function questionnairePath(electionId: number): string {
  return `/elecciones/${electionId}/cuestionario`;
}

/** The Election id from a route segment, or `null` when it is not a valid id. */
export function parseElectionId(raw: string | undefined): number | null {
  if (raw === undefined || !ELECTION_ID_PATTERN.test(raw)) {
    return null;
  }
  const id = Number(raw);
  return id <= MAX_ELECTION_ID ? id : null;
}
