import { useId, useState, type ReactNode } from "react";

import { ExpandMoreIcon } from "../../ui/icons";

/**
 * A collapsed-by-default Level 1 card (DESIGN.md "Expandable card"): the
 * heading holds a full-width button with a decorative leading icon tile and a
 * trailing chevron, and the button shows or hides the panel below it (WAI-ARIA
 * accordion pattern, so the heading stays a heading).
 */
export function ExpandableCard({
  title,
  icon,
  children,
}: {
  readonly title: string;
  readonly icon: ReactNode;
  readonly children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const titleId = `${id}-title`;
  const panelId = `${id}-panel`;
  return (
    <section className="expandable-card" aria-labelledby={titleId}>
      <h2 id={titleId} className="expandable-card__heading">
        <button
          type="button"
          className="expandable-card__toggle"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => setExpanded((value) => !value)}
        >
          <span className="expandable-card__icon">{icon}</span>
          <span className="expandable-card__title">{title}</span>
          <span className="expandable-card__chevron">
            <ExpandMoreIcon />
          </span>
        </button>
      </h2>
      <div id={panelId} className="expandable-card__panel" hidden={!expanded}>
        {children}
      </div>
    </section>
  );
}
