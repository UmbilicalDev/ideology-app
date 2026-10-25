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
