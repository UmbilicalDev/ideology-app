import type { Election } from "@ideology-app/core";

/**
 * Parties left out of an Election's Dataset Version, explained on the results
 * screens (own result and Share Link) above the ranking. Keyed by Election
 * type and date, not id, so it holds in every database. Copy from the user
 * (2026-11-20; Frente Obrero added and the text made plural 2026-11-22); the
 * EAJ-PNV reason is recorded in
 * `data/elections/es-general-2026-11-29/election.toml`.
 */
const EXCLUDED_PARTIES: Readonly<Record<string, readonly string[]>> = {
  "general/2026-11-29": [
    "El PNV (EAJ-PNV) y Frente Obrero no disponen de un programa electoral con suficientes " +
      "propuestas concretas y definidas para calcular su afinidad política. Por este motivo, " +
      "no se incluyen en los resultados.",
  ],
};

export function excludedPartiesFor(election: Pick<Election, "type" | "date">): readonly string[] {
  return EXCLUDED_PARTIES[`${election.type}/${election.date}`] ?? [];
}

export function ExcludedPartiesNotice({ notes }: { readonly notes: readonly string[] }) {
  if (notes.length === 0) return null;
  return (
    <div className="excluded-parties" role="note" aria-label="Partidos no incluidos en el cálculo">
      <p className="excluded-parties__title">Partidos no incluidos en el cálculo</p>
      {notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
    </div>
  );
}
