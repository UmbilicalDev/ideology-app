import { useState } from "react";

export type PartyLogoSize = "ranking" | "breakdown";

// Placeholder geometry in SVG user units. The font size (10) and line height
// (12) match `--party-logo-placeholder-font`; 0.72em is a generous advance for
// upper-case Inter at weight 600.
const FONT_SIZE = 10;
const ADVANCE = 0.72 * FONT_SIZE;
const LINE_HEIGHT = 12;
const PADDING = 2;
const MIN_SIDE = 28;
// Baseline below the line's centre, about half the cap height.
const BASELINE_OFFSET = 0.35 * FONT_SIZE;
const SPLIT_MIN_LENGTH = 5;

export interface PlaceholderLine {
  readonly text: string;
  /** Baseline y of the line, in user units. */
  readonly y: number;
}

export interface PlaceholderLayout {
  readonly lines: readonly PlaceholderLine[];
  readonly width: number;
  readonly height: number;
  /** Centre x for `text-anchor="middle"`. */
  readonly x: number;
}

function charCount(text: string): number {
  return Array.from(text).length;
}

function splitLines(shortName: string): string[] {
  const name = shortName.trim();
  if (charCount(name) < SPLIT_MIN_LENGTH) return [name];
  const at = name.search(/[ -]/);
  if (at === -1) return [name];
  // A space is dropped; a hyphen stays at the end of the first line.
  const first = name[at] === "-" ? name.slice(0, at + 1) : name.slice(0, at);
  const second = name.slice(at + 1).trim();
  const lines = [first.trim(), second].filter((line) => line.length > 0);
  return lines.length === 0 ? [name] : lines;
}

/**
 * The placeholder's lines and viewBox for a Party short name (DESIGN.md
 * "Party logo"). Pure. At most 2 lines; the viewBox is at least 28x28 and
 * grows with the text, so `preserveAspectRatio="xMidYMid meet"` scales any
 * length down to fit inside the tile.
 */
export function placeholderLayout(shortName: string): PlaceholderLayout {
  const texts = splitLines(shortName);
  const longest = Math.max(...texts.map(charCount));
  const width = Math.max(MIN_SIDE, longest * ADVANCE + 2 * PADDING);
  const height = Math.max(MIN_SIDE, texts.length * LINE_HEIGHT + 2 * PADDING);
  const top = (height - texts.length * LINE_HEIGHT) / 2;
  const lines = texts.map((text, i) => ({
    text,
    y: top + i * LINE_HEIGHT + LINE_HEIGHT / 2 + BASELINE_OFFSET,
  }));
  return { lines, width, height, x: width / 2 };
}

/**
 * The party-logo tile (DESIGN.md "Party logo"): the same fixed-size, white,
 * bordered tile for every Party, holding its logo from the same-origin
 * `logoUrl`, or a short-name placeholder when there is no logo or it fails
 * to load. Decorative: the Party name is text next to it. Never lazy-loaded:
 * logos are preloaded in Dataset Version order (`preloadPartyLogos`).
 */
export function PartyLogo({
  logoUrl,
  shortName,
  size,
}: {
  readonly logoUrl: string | null;
  readonly shortName: string;
  readonly size: PartyLogoSize;
}) {
  return (
    <span className={`party-logo party-logo--${size}`} aria-hidden="true">
      <TileContent key={logoUrl ?? ""} logoUrl={logoUrl} shortName={shortName} />
    </span>
  );
}

function TileContent({ logoUrl, shortName }: { readonly logoUrl: string | null; readonly shortName: string }) {
  const [failed, setFailed] = useState(false);
  if (logoUrl === null || failed) {
    return <Placeholder shortName={shortName} />;
  }
  return (
    <img
      className="party-logo__img"
      src={logoUrl}
      alt=""
      width="256"
      height="256"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}

function Placeholder({ shortName }: { readonly shortName: string }) {
  const layout = placeholderLayout(shortName);
  return (
    <svg
      className="party-logo__placeholder"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      focusable="false"
    >
      <text className="party-logo__text" textAnchor="middle">
        {layout.lines.map((line) => (
          <tspan key={line.y} x={layout.x} y={line.y}>
            {line.text}
          </tspan>
        ))}
      </text>
    </svg>
  );
}
