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

// Shield with a check: the AI disclosure on the Questionnaire and Landing.
export function ShieldIcon() {
  return (
    <Icon>
      <path d="M12 3l7 3v5c0 4.5-3 8.3-7 9.5-4-1.2-7-5-7-9.5V6z" />
      <path d="M9 12l2 2 4-4" />
    </Icon>
  );
}

// Filled robot head (the user's ic_robot.svg, recoloured to currentColor):
// the AI content card on the Landing.
export function RobotIcon() {
  return (
    <svg
      className="icon"
      aria-hidden="true"
      focusable="false"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="currentColor"
    >
      <path d="M4,15q-1.25,0-2.13-0.88T1,12T1.88,9.88T4,9V7Q4,6.18 4.59,5.59T6,5H9Q9,3.75 9.88,2.88T12,2t2.13,0.88T15,5h3q0.82,0 1.41,0.59Q20,6.18 20,7V9q1.25,0 2.13,0.88T23,12t-0.88,2.13T20,15v4q0,0.82-0.59,1.41T18,21H6q-0.82,0-1.41-0.59T4,19V15Zm6.06-2.44q0.44-0.44 0.44-1.06t-0.44-1.06T9,10T7.94,10.44T7.5,11.5t0.44,1.06T9,13t1.06-0.44Zm6,0q0.44-0.44 0.44-1.06t-0.44-1.06T15,10t-1.06,0.44T13.5,11.5t0.44,1.06T15,13t1.06-0.44ZM8,17h8V15H8v2ZM6,19H18V7H6V19Zm6-6Z" />
    </svg>
  );
}

// Filled test tube (the user's ic_test.svg, recoloured to currentColor):
// the Landing trial notice.
export function TestTubeIcon() {
  return (
    <svg
      className="icon"
      aria-hidden="true"
      focusable="false"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="currentColor"
    >
      <path d="M12,22q-2.07,0-3.54-1.46T7,17V8Q6.18,8 5.59,7.41T5,6V4Q5,3.17 5.59,2.59T7,2H17q0.82,0 1.41,0.59T19,4V6q0,0.82-0.59,1.41T17,8v9q0,2.07-1.46,3.54T12,22ZM7,6H17V4H7V6Zm7.13,13.13Q15,18.25 15,17H12V15h3V13H12V11h3V8H9v9q0,1.25 0.88,2.13T12,20t2.13-0.88ZM7,6V4V6Z" />
    </svg>
  );
}

// Trailing chevron of an expandable card; CSS turns it when expanded.
export function ExpandMoreIcon() {
  return (
    <Icon>
      <path d="M6 9l6 6 6-6" />
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
