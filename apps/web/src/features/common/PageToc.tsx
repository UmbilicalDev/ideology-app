import { useEffect, useRef, useState } from "react";

export interface TocEntry {
  /** The id of the section heading the entry jumps to. */
  readonly id: string;
  readonly label: string;
}

/** A section is current once its heading reaches this share of the viewport height. */
export const ACTIVE_LINE = 0.3;

/**
 * The entry being read: the last heading at or above the active line, the
 * first entry above the first heading, and the last entry once the page cannot
 * scroll further (a short last section never reaches the line).
 */
export function currentEntryId(entries: readonly TocEntry[]): string | null {
  const first = entries[0];
  if (first === undefined) return null;
  const root = document.documentElement;
  const scrollable = root.scrollHeight > window.innerHeight;
  if (scrollable && window.scrollY + window.innerHeight >= root.scrollHeight - 2) {
    return entries[entries.length - 1]?.id ?? null;
  }
  const line = window.innerHeight * ACTIVE_LINE;
  let current = first.id;
  for (const entry of entries) {
    const heading = document.getElementById(entry.id);
    if (heading !== null && heading.getBoundingClientRect().top <= line) current = entry.id;
  }
  return current;
}

/**
 * "En esta página" (DESIGN.md "Page index"): in-page links to a long page's
 * sections. A sticky column beside the text from 1024px; above the text below.
 * The entry being read is marked with `aria-current="location"` as the Voter
 * scrolls; a clicked entry stays marked until the Voter scrolls by hand.
 */
export function PageToc({ entries }: { readonly entries: readonly TocEntry[] }) {
  const [activeId, setActiveId] = useState<string | null>(() => entries[0]?.id ?? null);
  // The entry the Voter clicked, kept while the jump scrolls the page.
  const clicked = useRef<string | null>(null);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const heading = clicked.current === null ? null : document.getElementById(clicked.current);
      if (heading !== null) {
        const top = heading.getBoundingClientRect().top;
        if (top >= 0 && top < window.innerHeight) return;
      }
      clicked.current = null;
      setActiveId(currentEntryId(entries));
    };
    const onScroll = () => {
      if (frame === 0) frame = window.requestAnimationFrame(update);
    };
    const release = () => {
      clicked.current = null;
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    window.addEventListener("wheel", release, { passive: true });
    window.addEventListener("touchstart", release, { passive: true });
    window.addEventListener("keydown", release);
    return () => {
      if (frame !== 0) window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("wheel", release);
      window.removeEventListener("touchstart", release);
      window.removeEventListener("keydown", release);
    };
  }, [entries]);

  return (
    <nav className="page-toc" aria-labelledby="page-toc-title">
      <p id="page-toc-title" className="page-toc__title">
        En esta página
      </p>
      <ul className="page-toc__list">
        {entries.map((entry) => (
          <li key={entry.id}>
            <a
              className="page-toc__link"
              href={`#${entry.id}`}
              aria-current={entry.id === activeId ? "location" : undefined}
              onClick={() => {
                clicked.current = entry.id;
                setActiveId(entry.id);
              }}
            >
              {entry.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
