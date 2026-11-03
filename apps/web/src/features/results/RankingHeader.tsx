import { useId, useState } from "react";

import { AlertIcon } from "../../ui/icons";

/**
 * The top of the ranking card (DESIGN.md "Ranking warning"): the intro (or
 * the no-scores prompt) with an alert button at the top right that shows
 * the "not a voting recommendation" warning below it, like the Share Link
 * info toggle.
 */
export function RankingHeader({ text, warning }: { readonly text: string; readonly warning: string }) {
  const [open, setOpen] = useState(false);
  const warningId = useId();
  return (
    <>
      <div className="ranking-header">
        <p className="ranking-header__text">{text}</p>
        <button
          type="button"
          className="icon-button ranking-header__toggle"
          aria-label="Aviso sobre estos resultados"
          aria-expanded={open}
          aria-controls={warningId}
          onClick={() => setOpen((previous) => !previous)}
        >
          <AlertIcon />
        </button>
      </div>
      <p id={warningId} className="ranking-warning" hidden={!open}>
        {warning}
      </p>
    </>
  );
}
