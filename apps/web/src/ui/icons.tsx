import type { ReactNode } from "react";

// Decorative line icons drawn for this app (DESIGN.md "Icons"): currentColor,
// aria-hidden, sized by CSS. The meaning always lives in the adjacent text.
function Icon({ className, children }: { readonly className?: string; readonly children: ReactNode }) {
  return (
    <svg
      className={className === undefined ? "icon" : `icon ${className}`}
      aria-hidden="true"
      focusable="false"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      {children}
    </svg>
  );
}

export function ShareIcon() {
  return (
    <Icon>
      <circle cx="18" cy="5.5" r="2.5" />
      <circle cx="6" cy="12" r="2.5" />
      <circle cx="18" cy="18.5" r="2.5" />
      <path d="M8.2 10.8l7.6-4.1M8.2 13.2l7.6 4.1" />
    </Icon>
  );
}

export function LinkIcon() {
  return (
    <Icon>
      <path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" />
    </Icon>
  );
}

export function InfoIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5M12 7.5v.01" />
    </Icon>
  );
}

// "Aviso": a circle with an exclamation mark (the info icon turned over).
export function AlertIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5V13M12 16.5v.01" />
    </Icon>
  );
}

export function ExternalLinkIcon() {
  return (
    <Icon>
      <path d="M14 4h6v6M20 4l-9 9" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </Icon>
  );
}

// Outline by default; CSS fills it to show a pressed or non-zero state, so
// the shape carries the state, not only the colour.
export function StarIcon({ className }: { readonly className: string }) {
  return (
    <Icon className={className}>
      <path d="M12 2.5l2.94 5.96 6.56.95-4.75 4.63 1.12 6.54L12 17.5l-5.87 3.08 1.12-6.54L2.5 9.41l6.56-.95z" />
    </Icon>
  );
}

export function ArrowForwardIcon() {
  return (
    <Icon>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Icon>
  );
}

export function ArrowBackIcon() {
  return (
    <Icon>
      <path d="M19 12H5M11 6l-6 6 6 6" />
    </Icon>
  );
}

// "Step over": an arrow arcing over a dot, for a skipped Statement.
export function StepOverIcon({ className }: { readonly className?: string }) {
  return (
    <Icon className={className}>
      <path d="M4.5 14.5a7.5 7.5 0 0 1 14-3.5" />
      <path d="M19.5 6v5h-5" />
      <circle cx="12" cy="18.5" r="1.75" />
    </Icon>
  );
}

export function HomeIcon() {
  return (
    <Icon>
      <path d="M4 10.5L12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5H15v-6H9v6H5.5A1.5 1.5 0 0 1 4 19z" />
    </Icon>
  );
}

// The answer scale (DESIGN.md "Icons"): one thumb per grade, a double thumb
// for "Muy", up and down together for the neutral point. Drawn on a wider
// 32x24 canvas (`icon--wide`) so the pairs stay legible; each glyph is drawn
// pointing up and flipped vertically for "down". The label next to it always
// carries the meaning.
const THUMB = (
  <>
    <path d="M3 10.5h3.5V20H3z" />
    <path d="M6.5 10.5L10 3.5c1.5 0 2.6 1.2 2.3 2.7l-.6 3.3H18a2 2 0 0 1 2 2.3l-1.2 6.5a2 2 0 0 1-2 1.7H6.5" />
  </>
);

// The "Muy" glyph, supplied by the product owner (a filled 24x24 shape).
const DOUBLE_THUMB =
  "M17.83,17L21,9.57q0-0.07 0-0.29T21,9q-0.4,0-1.29,0T17.85,9T16,9T14.7,9l0.47-3.35L13.8,7.02" +
  "q-0.2-0.2-0.7-0.71T12.4,5.6L16,2l0.8,0.8q0.35,0.35 0.49,0.79T17.35,4.5L17,7h4q0.83,0 1.41,0.59" +
  "T23,9V9.57q0,0.2-0.04,0.4q-0.04,0.2-0.11,0.4l-2.32,5.4q-0.25,0.55-0.75,0.89T18.68,17H17.83Z" +
  "M6,21H1V11H6v2H3v6H6v2Zm6.68,0H4V12l6-6l0.8,0.8q0.35,0.35 0.49,0.79T11.35,8.5L11,11h4" +
  "q0.83,0 1.41,0.59Q17,12.18 17,13v0.6q0,0.2-0.04,0.39t-0.11,0.39L14.53,19.8q-0.25,0.55-0.75,0.88" +
  "T12.68,21Zm0-2L15,13.6V13H8.7L9.18,9.65L6,12.83V19h6.68ZM6,19V12.83V13v0.6V19Z";

type ThumbProps = { readonly className?: string };

function WideIcon({ className, children }: ThumbProps & { readonly children: ReactNode }) {
  return (
    <svg
      className={className === undefined ? "icon icon--wide" : `icon icon--wide ${className}`}
      aria-hidden="true"
      focusable="false"
      width="32"
      height="24"
      viewBox="0 0 32 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      {children}
    </svg>
  );
}

// A pair in the neutral icon is drawn at 75 %, with a wider stroke so the
// line weight matches the single thumb.
const PAIR_SCALE = 0.75;
const UP = "translate(4.5 0)";
const DOWN = "matrix(1 0 0 -1 4.5 24)";
const PAIR_UP_LEFT = `matrix(${PAIR_SCALE} 0 0 ${PAIR_SCALE} -1.75 3.2)`;
const PAIR_DOWN_RIGHT = `matrix(${PAIR_SCALE} 0 0 -${PAIR_SCALE} 14.25 20.8)`;
const DOUBLE_UP = "translate(4 0)";
const DOUBLE_DOWN = "matrix(1 0 0 -1 4 24)";

function Thumbs({ className, marks }: ThumbProps & { readonly marks: readonly string[] }) {
  const strokeWidth = marks.length > 1 ? 1.75 / PAIR_SCALE : undefined;
  return (
    <WideIcon className={className}>
      {marks.map((transform) => (
        <g key={transform} transform={transform} strokeWidth={strokeWidth}>
          {THUMB}
        </g>
      ))}
    </WideIcon>
  );
}

function DoubleThumb({ className, transform }: ThumbProps & { readonly transform: string }) {
  return (
    <WideIcon className={className}>
      <path d={DOUBLE_THUMB} transform={transform} fill="currentColor" stroke="none" />
    </WideIcon>
  );
}

export function ThumbUpIcon({ className }: ThumbProps) {
  return <Thumbs className={className} marks={[UP]} />;
}

export function ThumbDownIcon({ className }: ThumbProps) {
  return <Thumbs className={className} marks={[DOWN]} />;
}

export function DoubleThumbUpIcon({ className }: ThumbProps) {
  return <DoubleThumb className={className} transform={DOUBLE_UP} />;
}

export function DoubleThumbDownIcon({ className }: ThumbProps) {
  return <DoubleThumb className={className} transform={DOUBLE_DOWN} />;
}

export function ThumbUpDownIcon({ className }: ThumbProps) {
  return <Thumbs className={className} marks={[PAIR_UP_LEFT, PAIR_DOWN_RIGHT]} />;
}

export function FeedbackIcon() {
  return (
    <Icon>
      <path d="M5 4.5h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-7l-4.5 3.5v-3.5H5a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z" />
      <path d="M7.5 9h9M7.5 13h6" />
    </Icon>
  );
}

export function CloseIcon() {
  return (
    <Icon>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  );
}

export function CheckIcon() {
  return (
    <Icon>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Icon>
  );
}

export function CheckCircleIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.7 2.7L16 9.8" />
    </Icon>
  );
}

export function MailIcon() {
  return (
    <Icon>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <path d="M3.5 7l8.5 6 8.5-6" />
    </Icon>
  );
}

export function MenuIcon() {
  return (
    <Icon>
      <path d="M4 6.5h16M4 12h16M4 17.5h16" />
    </Icon>
  );
}

// Sidebar navigation: a ballot box, an open book and a chip.
export function BallotIcon() {
  return (
    <Icon>
      <path d="M4 11h16v8.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19.5z" />
      <path d="M8 11V4.5A1.5 1.5 0 0 1 9.5 3h5A1.5 1.5 0 0 1 16 4.5V11" />
      <path d="M10 7l1.5 1.5L14 6M4 15h16" />
    </Icon>
  );
}

export function ChevronLeftIcon() {
  return (
    <Icon>
      <path d="M14.5 6l-6 6 6 6" />
    </Icon>
  );
}

export function ChevronRightIcon() {
  return (
    <Icon>
      <path d="M9.5 6l6 6-6 6" />
    </Icon>
  );
}

export function PauseIcon() {
  return (
    <Icon>
      <path d="M9 6.5v11M15 6.5v11" />
    </Icon>
  );
}

export function PlayIcon() {
  return (
    <Icon>
      <path d="M8.5 6.2v11.6L18 12z" />
    </Icon>
  );
}

export function BookIcon() {
  return (
    <Icon>
      <path d="M12 6.5C10.5 5 8 4.5 4 4.5v13c4 0 6.5.5 8 2 1.5-1.5 4-2 8-2v-13c-4 0-6.5.5-8 2z" />
      <path d="M12 6.5v13" />
    </Icon>
  );
}

export function ChipIcon() {
  return (
    <Icon>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9.5 9.5h5v5h-5zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
    </Icon>
  );
}

export function CalendarIcon() {
  return (
    <Icon>
      <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </Icon>
  );
}

export function ShieldIcon() {
  return (
    <Icon>
      <path d="M12 3l7 3v5c0 4.5-3 8.3-7 9.5-4-1.2-7-5-7-9.5V6z" />
      <path d="M9 12l2 2 4-4" />
    </Icon>
  );
}

// Simplified brand marks drawn for this app (DESIGN.md "Icons"): filled in
// currentColor, never in brand colours, aria-hidden. The share target's
// caption names the network and its accessible name says the action.
function BrandIcon({ children }: { readonly children: ReactNode }) {
  return (
    <svg
      className="icon"
      aria-hidden="true"
      focusable="false"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="currentColor"
      stroke="none"
      fillRule="evenodd"
    >
      {children}
    </svg>
  );
}

export function FacebookIcon() {
  return (
    <BrandIcon>
      <path d="M13.6 21v-7.6h2.6l.4-3h-3V8.6c0-.9.3-1.5 1.6-1.5h1.6V4.4c-.3 0-1.2-.1-2.3-.1-2.3 0-3.8 1.4-3.8 3.9v2.2H8.1v3h2.6V21z" />
    </BrandIcon>
  );
}

export function WhatsAppIcon() {
  return (
    <BrandIcon>
      <path d="M12 3a9 9 0 1 1-4.3 16.9L3 21l1.2-4.5A9 9 0 0 1 12 3zm0 1.7a7.3 7.3 0 0 0-6.2 11.1l.2.3-.7 2.6 2.7-.7.3.2A7.3 7.3 0 1 0 12 4.7z" />
      <path d="M9.1 7.9c.3-.3.8-.3 1 .1l.9 1.7c.2.3.1.7-.2.9l-.6.5c.5 1.1 1.4 2 2.5 2.5l.5-.6c.2-.3.6-.4.9-.2l1.7.9c.4.2.4.7.1 1-.9 1-2.2 1.2-3.4.6a8.6 8.6 0 0 1-3.9-3.9c-.6-1.2-.4-2.5.5-3.5z" />
    </BrandIcon>
  );
}

export function InstagramIcon() {
  return (
    <BrandIcon>
      <path d="M8 3h8a5 5 0 0 1 5 5v8a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5V8a5 5 0 0 1 5-5zm0 1.8A3.2 3.2 0 0 0 4.8 8v8A3.2 3.2 0 0 0 8 19.2h8a3.2 3.2 0 0 0 3.2-3.2V8A3.2 3.2 0 0 0 16 4.8z" />
      <path d="M12 7.6a4.4 4.4 0 1 1 0 8.8 4.4 4.4 0 0 1 0-8.8zm0 1.8a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2z" />
      <circle cx="16.9" cy="7.1" r="1.1" />
    </BrandIcon>
  );
}

export function XIcon() {
  return (
    <BrandIcon>
      <path d="M3.8 4h4.9l11.5 16h-4.9z" />
      <path d="M18.4 4h1.9l-6.6 7.6-1-1.4zM4 20l6.9-7.9 1 1.4L5.9 20z" />
    </BrandIcon>
  );
}
