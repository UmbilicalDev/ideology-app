import type { HttpResponseLike } from "@ideology-app/core";

export function jsonResponse(body: unknown, status = 200): HttpResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  };
}

/** A non-JSON error response, like the server's `text/plain` 500. */
export function textResponse(status: number): HttpResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.reject(new SyntaxError("Unexpected token 'I'")),
  };
}

export function electionJson(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    country: "ES",
    type: "general",
    date: "2023-07-23",
    name: "Generales 2023",
    status: "active",
    published_dataset_version_id: 1,
    ...overrides,
  };
}

/**
 * A `DatasetVersionOut` body: `statements` Statements `Afirmación de prueba {i}`
 * (ids 100 + i, positions 1..n) and two Parties with one Position per
 * Statement; the second Party has `no_stance` on Statement 1.
 */
export function datasetVersionJson({
  statements,
  electionId = 1,
  id = 1,
}: {
  readonly statements: number;
  readonly electionId?: number;
  readonly id?: number;
}): Record<string, unknown> {
  const items = Array.from({ length: statements }, (_, i) => ({
    id: 100 + i + 1,
    position: i + 1,
    text: `Afirmación de prueba ${i + 1}`,
    topic: "economía",
  }));
  const evidence = { quote: "Cita.", page: 1, url: null, source_document_id: 1 };
  return {
    id,
    election_id: electionId,
    created_at: "2026-10-20T09:30:00Z",
    statements: items,
    parties: [
      {
        id: 1,
        name: "Partido Uno",
        short_name: "P1",
        positions: items.map((s) => ({ statement_id: s.id, value: 1, evidence })),
      },
      {
        id: 2,
        name: "Partido Dos",
        short_name: "P2",
        positions: items.map((s, i) =>
          i === 0
            ? { statement_id: s.id, value: "no_stance", evidence: null }
            : { statement_id: s.id, value: -1, evidence },
        ),
      },
    ],
  };
}
