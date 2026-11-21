import { NEUTRAL, positionSide, type AnswerValue, type ScaleValue } from "@ideology-app/core";

import { ThumbDownIcon, ThumbUpDownIcon, ThumbUpIcon } from "../ui/icons";

/** -1 against, 0 neutral, 1 in favour. */
export type Side = -1 | 0 | 1;

const SIDE_ICONS = {
  [-1]: ThumbDownIcon,
  0: ThumbUpDownIcon,
  1: ThumbUpIcon,
} as const;

/**
 * The icon of a side, shared by the Questionnaire options and the results
 * matrix. Decorative: the label or accessible name next to it carries the
 * meaning (DESIGN.md "Icons").
 */
export function SideIcon({ side, className }: { readonly side: Side; readonly className?: string }) {
  const Glyph = SIDE_ICONS[side];
  return <Glyph className={className} />;
}

export function answerSide(value: AnswerValue): Side {
  return value === NEUTRAL ? 0 : value;
}

export function stanceSide(value: ScaleValue): Side {
  return positionSide(value) ?? 0;
}
