import type { ReactNode } from "react";

/**
 * A copy control's two faces stacked in one grid cell (DESIGN.md "Copy
 * feedback"), so swapping to `¡Copiado!` never changes its size. Only the
 * active face is exposed to assistive technology.
 */
export function CopySwap({
  copied,
  idle,
  done,
}: {
  readonly copied: boolean;
  readonly idle: ReactNode;
  readonly done: ReactNode;
}) {
  return (
    <span className="copy-swap" data-copied={copied}>
      <span className="copy-swap__face copy-swap__idle" aria-hidden={copied}>
        {idle}
      </span>
      <span className="copy-swap__face copy-swap__done" aria-hidden={!copied}>
        {done}
      </span>
    </span>
  );
}
