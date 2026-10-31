export interface TocEntry {
  /** The id of the section heading the entry jumps to. */
  readonly id: string;
  readonly label: string;
}

/**
 * "En esta página" (DESIGN.md "Page index"): in-page links to a long page's
 * sections. A sticky column beside the text from 1024px; above the text below.
 */
export function PageToc({ entries }: { readonly entries: readonly TocEntry[] }) {
  return (
    <nav className="page-toc" aria-labelledby="page-toc-title">
      <p id="page-toc-title" className="page-toc__title">
        En esta página
      </p>
      <ul className="page-toc__list">
        {entries.map((entry) => (
          <li key={entry.id}>
            <a className="page-toc__link" href={`#${entry.id}`}>
              {entry.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
