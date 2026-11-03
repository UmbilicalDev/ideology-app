import type { ScaleValue } from "@ideology-app/core";

import {
  DoubleThumbDownIcon,
  DoubleThumbUpIcon,
  ThumbDownIcon,
  ThumbUpDownIcon,
  ThumbUpIcon,
} from "../ui/icons";

const SCALE_ICONS = {
  [-2]: DoubleThumbDownIcon,
  [-1]: ThumbDownIcon,
  0: ThumbUpDownIcon,
  1: ThumbUpIcon,
  2: DoubleThumbUpIcon,
} as const;

/**
 * The icon of a scale value, shared by the Questionnaire options and the
 * results matrix. Decorative: the label or accessible name next to it carries
 * the meaning (DESIGN.md "Icons").
 */
export function ScaleIcon({ value, className }: { readonly value: ScaleValue; readonly className?: string }) {
  const Glyph = SCALE_ICONS[value];
  return <Glyph className={className} />;
}
